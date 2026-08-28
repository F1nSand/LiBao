import { computed, reactive, ref, type ComputedRef } from 'vue'
import { streamChatAt, streamTaskResume } from '@/api/sse'
import type { ChatRequest, SseEnvelope, TokenUsage } from '@/types'
import type { AgentSwitchPayload, DonePayload, Message, MessageSealPayload, ToolResultPayload } from '@/types'
import { flushNow, throttleByRaf } from '@/utils/rAF'

/**
 * 流式消息渲染状态机（docs/02 §5.3）：按会话隔离（多流）：
 * message_start → token* → tool_call → tool_result(占位/回填) → … → done
 * interrupt → 确认弹窗 → confirmInterrupt 续流（复用 segments/toolCalls 不回滚）
 *
 * 每个会话一个 ConvCtx（state/controller/pendingText/timers），`state` = 当前查看会话的 entry；
 * 切换会话用 setConversation（不 reset），后台流继续写入各自的 ctx → 切回可见切换前思考/工具调用。
 */

export type StreamSegment =
  | { kind: 'text'; id: string; text: string }
  | { kind: 'tool'; id: string; cardId: string }
  | { kind: 'agent'; id: string; from: string; to: string; reason?: string }
  | { kind: 'thinking'; id: string; text: string }

export type ToolCardStatus =
  | 'pending'
  | 'running'
  | 'awaiting_confirm'
  | 'done'
  | 'error'
  | 'timeout'
  | 'cancelled'

export interface ToolCallCardState {
  tool_call_id: string
  tool_name: string
  input: unknown
  require_confirm?: boolean
  status: ToolCardStatus
  summary?: string
  structured?: unknown
  job_ref?: string
  durationMs?: number
  startedAt: number
  error?: string
}

export interface InterruptInfo {
  node_id: string
  payload?: unknown
  confirm_required?: boolean
  task_id?: string
}

export interface StreamError {
  code: number
  message: string
  retryable?: boolean
}

export interface StreamState {
  taskId: string | null
  messageId: string | null
  conversationId: string | null
  segments: StreamSegment[]
  partialText: string
  toolCalls: Record<string, ToolCallCardState>
  status: string | null
  contextMetrics?: Record<string, unknown>
  interrupted: InterruptInfo | null
  error: StreamError | null
  finished: boolean
  tokenUsage?: TokenUsage
  cost?: number
  streaming: boolean
}

export interface UseChatStreamOptions {
  placeholderTtlMs?: number
  /** done 事件携带最终持久化消息时回调（触发 chat store 刷新） */
  onPersistedMessage?: (message: unknown) => void
}

export interface UseChatStreamReturn {
  /** 当前查看会话的流式状态（切换会话经 setConversation 指向对应 entry） */
  state: ComputedRef<StreamState>
  start(req: ChatRequest): Promise<void>
  stop(): void
  confirmInterrupt(approved: boolean, extra?: Record<string, unknown>): Promise<void>
  /** 切换当前查看的会话（不 reset，后台流继续写入各自 ctx） */
  setConversation(convId: string): void
}

let uidCounter = 0
function segId(): string {
  uidCounter += 1
  return `seg_${uidCounter}`
}

/** 每个会话的流式上下文：独立 state + controller + pendingText + timers */
interface ConvCtx {
  convId: string
  state: StreamState
  controller: AbortController | null
  pendingText: string
  timers: Map<string, ReturnType<typeof setTimeout>>
  flush: () => void
}

function createEmptyState(convId: string | null): StreamState {
  return reactive({
    taskId: null,
    messageId: null,
    conversationId: convId,
    segments: [],
    partialText: '',
    toolCalls: {},
    status: null,
    interrupted: null,
    error: null,
    finished: false,
    streaming: false,
  })
}

export function useChatStream(opts: UseChatStreamOptions = {}): UseChatStreamReturn {
  const placeholderTtlMs = opts.placeholderTtlMs ?? 120_000

  const convCtxs = new Map<string, ConvCtx>()
  let currentConvKey = '__none__'
  const currentState = ref<StreamState>(createEmptyState(null))

  function getCtx(convId: string): ConvCtx {
    let ctx = convCtxs.get(convId)
    if (!ctx) {
      ctx = {
        convId,
        state: createEmptyState(convId),
        controller: null,
        pendingText: '',
        timers: new Map(),
        flush: () => {},
      }
      ctx.flush = throttleByRaf(() => flushText(ctx!))
      convCtxs.set(convId, ctx)
    }
    return ctx
  }

  function currentCtx(): ConvCtx {
    return getCtx(currentConvKey)
  }

  /** 文本追加到"唯一"文本段（回复气泡正文；活动区在气泡上方，视觉位置不依赖数组序） */
  function flushText(ctx: ConvCtx): void {
    if (!ctx.pendingText) return
    const first = ctx.state.segments.find((s) => s.kind === 'text')
    if (first) {
      first.text += ctx.pendingText
    } else {
      ctx.state.segments.unshift({ kind: 'text', id: segId(), text: ctx.pendingText })
    }
    ctx.state.partialText += ctx.pendingText
    ctx.pendingText = ''
  }

  function clearTimers(ctx: ConvCtx): void {
    for (const t of ctx.timers.values()) clearTimeout(t)
    ctx.timers.clear()
  }

  /** 一轮思考完成：复位本轮流式段（保留 taskId/conversationId/messageId 跨轮续用），下一轮继续 */
  function sealRound(ctx: ConvCtx): void {
    ctx.state.segments = []
    ctx.state.partialText = ''
    ctx.state.toolCalls = {}
    ctx.state.status = 'running'
  }

  function findCard(p: { tool_call_id?: string; job_ref?: string }, ctx: ConvCtx): ToolCallCardState | undefined {
    if (p.tool_call_id && ctx.state.toolCalls[p.tool_call_id]) return ctx.state.toolCalls[p.tool_call_id]
    if (p.job_ref) return Object.values(ctx.state.toolCalls).find((c) => c.job_ref === p.job_ref)
    return undefined
  }

  function startPlaceholderTimer(cardId: string, ctx: ConvCtx): void {
    const existing = ctx.timers.get(cardId)
    if (existing) clearTimeout(existing)
    ctx.timers.set(
      cardId,
      setTimeout(() => {
        const card = ctx.state.toolCalls[cardId]
        if (card && card.status === 'running') card.status = 'timeout'
      }, placeholderTtlMs),
    )
  }

  function handleToolResult(p: ToolResultPayload, ctx: ConvCtx): void {
    const card = findCard(p, ctx)
    if (!card) {
      // 迟到事件兜底：创建卡片
      const id = p.tool_call_id ?? p.job_ref ?? `tc_late`
      const c: ToolCallCardState = {
        tool_call_id: id,
        tool_name: p.tool_name,
        input: null,
        status: 'running',
        startedAt: Date.now(),
      }
      ctx.state.toolCalls[id] = c
      ctx.state.segments.push({ kind: 'tool', id: segId(), cardId: id })
      if (p.placeholder) {
        c.status = 'running'
        c.job_ref = p.job_ref
        startPlaceholderTimer(id, ctx)
      } else {
        c.status = p.ok ? 'done' : 'error'
        c.summary = p.summary
        c.structured = p.structured
        c.error = p.error
        c.durationMs = p.duration_ms
      }
      return
    }
    if (p.placeholder) {
      card.status = 'running'
      card.job_ref = p.job_ref
      startPlaceholderTimer(card.tool_call_id, ctx)
      return
    }
    const t = ctx.timers.get(card.tool_call_id)
    if (t) clearTimeout(t)
    card.status = p.ok ? 'done' : 'error'
    card.summary = p.summary
    card.structured = p.structured
    card.error = p.error
    card.durationMs = p.duration_ms ?? (Date.now() - card.startedAt)
  }

  function applyEvent(ev: SseEnvelope, ctx: ConvCtx): void {
    const s = ctx.state
    const p = ev.payload as Record<string, any>
    switch (ev.type) {
      case 'message_start': {
        s.taskId = p.task_id ?? s.taskId
        s.messageId = p.message_id
        s.conversationId = p.conversation_id
        s.segments = []
        s.partialText = ''
        s.status = 'running'
        s.finished = false
        s.error = null
        s.interrupted = null
        s.streaming = true
        break
      }
      case 'token': {
        ctx.pendingText += (p.text ?? '') as string
        ctx.flush()
        break
      }
      case 'tool_call': {
        const card: ToolCallCardState = {
          tool_call_id: p.tool_call_id,
          tool_name: p.tool_name,
          input: p.input,
          require_confirm: p.require_confirm,
          status: p.require_confirm ? 'awaiting_confirm' : 'running',
          startedAt: Date.now(),
        }
        s.toolCalls[card.tool_call_id] = card
        s.segments.push({ kind: 'tool', id: segId(), cardId: card.tool_call_id })
        break
      }
      case 'tool_result': {
        handleToolResult(p as ToolResultPayload, ctx)
        break
      }
      case 'interrupt': {
        s.taskId = p.task_id ?? s.taskId
        s.interrupted = {
          node_id: p.node_id,
          payload: p.payload,
          confirm_required: p.confirm_required,
          task_id: p.task_id,
        }
        s.status = 'waiting_confirm'
        s.streaming = false
        break
      }
      case 'status': {
        s.status = (p.status as string) ?? s.status
        s.contextMetrics = p.context_metrics
        break
      }
      case 'agent_switch': {
        // 多 Agent 切换（docs/03 §3.3）：以独立段混排进事件序（文本/工具/切换按序）
        const { from_agent: from, to_agent: to, reason } = p as AgentSwitchPayload
        s.segments.push({ kind: 'agent', id: segId(), from, to, reason })
        break
      }
      case 'thinking': {
        // 思考（docs/03 §3.3）：一轮思考累积到末段，不因分块堆叠多行
        const t = (p.text ?? '') as string
        const last = s.segments[s.segments.length - 1]
        if (last && last.kind === 'thinking') last.text += t
        else s.segments.push({ kind: 'thinking', id: segId(), text: t })
        break
      }
      case 'message': {
        // 逐轮消息封口（docs/03 §3 多消息扩展）：一轮思考（文本+工具）完成，追加为独立消息 + 复位段
        flushText(ctx)
        flushNow()
        const seal = p as MessageSealPayload
        // 透传本轮 token_usage/cost（封口载荷顶层字段；message 自带则优先，避免覆盖后端 serialize_message）
        let msg = seal.message
        if ((!msg.token_usage && seal.token_usage) || (msg.cost == null && seal.cost != null)) {
          msg = { ...msg }
          if (!msg.token_usage && seal.token_usage) msg.token_usage = seal.token_usage
          if (msg.cost == null && seal.cost != null) msg.cost = seal.cost
        }
        opts.onPersistedMessage?.(msg)
        sealRound(ctx)
        break
      }
      case 'done': {
        flushText(ctx)
        flushNow()
        const done = p as DonePayload
        s.tokenUsage = done.token_usage
        s.cost = done.cost
        s.finished = true
        s.streaming = false
        s.status = 'done'
        // 同上：done 顶层 token_usage/cost 兜底附到最终消息（仅最终轮有 cost）
        const m = done.message as Message | undefined
        if (m && ((!m.token_usage && done.token_usage) || (m.cost == null && done.cost != null))) {
          const msg = { ...m }
          if (!msg.token_usage && done.token_usage) msg.token_usage = done.token_usage
          if (msg.cost == null && done.cost != null) msg.cost = done.cost
          opts.onPersistedMessage?.(msg)
        } else {
          opts.onPersistedMessage?.(done.message)
        }
        break
      }
      case 'error': {
        flushNow()
        s.error = { code: p.code, message: p.message, retryable: p.retryable }
        s.finished = true
        s.streaming = false
        s.status = 'failed'
        break
      }
      default: {
        // run_progress / tool_exec：监视器预留，MVP 忽略
        break
      }
    }
  }

  function onError(e: Error, ctx: ConvCtx): void {
    // 用户主动停止或组件卸载触发的 Abort 不应伪装成可重试的业务失败。
    if (e.name === 'AbortError' || ctx.controller?.signal.aborted) {
      ctx.state.streaming = false
      return
    }
    ctx.state.error = { code: 50001, message: e.message, retryable: true }
    ctx.state.finished = true
    ctx.state.streaming = false
    ctx.state.status = 'failed'
  }

  /** 清空某个会话的流式状态（start 新流前调用；保留原响应式对象，引用稳定） */
  function resetCtx(ctx: ConvCtx): void {
    const s = ctx.state
    s.taskId = null
    s.messageId = null
    s.conversationId = ctx.convId
    s.segments = []
    s.partialText = ''
    s.toolCalls = {}
    s.status = null
    s.interrupted = null
    s.error = null
    s.finished = false
    s.streaming = false
    ctx.pendingText = ''
    clearTimers(ctx)
  }

  /** 切换当前查看的会话：state 指向该会话 entry（无则新建空态）；不 reset、不 abort 后台流 */
  function setConversation(convId: string): void {
    currentConvKey = convId
    currentState.value = getCtx(convId).state
  }

  async function start(req: ChatRequest): Promise<void> {
    const convId = req.conversation_id ?? '__new__'
    const ctx = getCtx(convId)
    resetCtx(ctx)
    currentConvKey = convId
    currentState.value = ctx.state
    ctx.state.streaming = true
    ctx.controller = new AbortController()
    try {
      await streamChatAt(
        '/api/v1/chat/stream',
        req,
        { onEvent: (ev) => applyEvent(ev, ctx), onError: (e) => onError(e, ctx) },
        ctx.controller.signal,
      )
    } finally {
      // 静默关流（无 done/error）兜底：避免 streaming 卡 true 导致输入框永久禁用
      if (!ctx.state.finished) ctx.state.streaming = false
      ctx.controller = null
    }
  }

  async function confirmInterrupt(
    approved: boolean,
    extra?: Record<string, unknown>,
  ): Promise<void> {
    const ctx = currentCtx()
    // fail-fast：interrupt 事件必须带 task_id，缺失即报错，不用 conversation_id 冒充（会误路由）
    const taskId = ctx.state.taskId ?? ''
    if (!taskId) {
      ctx.state.error = { code: 40001, message: '缺少 task_id，无法恢复中断', retryable: false }
      return
    }
    ctx.state.interrupted = null
    ctx.state.status = 'running'
    ctx.state.streaming = true
    ctx.controller = new AbortController()
    try {
      await streamTaskResume(
        taskId,
        { approved, ...extra },
        { onEvent: (ev) => applyEvent(ev, ctx), onError: (e) => onError(e, ctx) },
        ctx.controller.signal,
      )
    } finally {
      // 同上：静默关流兜底
      if (!ctx.state.finished) ctx.state.streaming = false
      ctx.controller = null
    }
  }

  function stop(): void {
    const ctx = currentCtx()
    flushText(ctx)
    flushNow()
    ctx.controller?.abort()
    clearTimers(ctx)
    ctx.state.streaming = false
  }

  const state = computed<StreamState>(() => currentState.value)

  return { state, start, stop, confirmInterrupt, setConversation }
}
