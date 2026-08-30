import { computed, reactive, ref, type ComputedRef } from 'vue'
import { streamChatAt, streamTaskEvents, streamTaskResume } from '@/api/sse'
import { cancelTask, getTaskStatus, recoverTask, type CancelTaskResult } from '@/api/task-control'
import type { ChatRequest, CheckpointAnchor, SseEnvelope, Task, TaskError, TaskStatus, TokenUsage } from '@/types'
import type { AgentSwitchPayload, DonePayload, Message, MessageSealPayload, ModelRetryPayload, ToolResultPayload } from '@/types'
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

export type AgentRunPhase =
  | 'idle'
  | 'starting'
  | 'running'
  | 'thinking'
  | 'tool'
  | 'delegating'
  | 'responding'
  | 'finalizing'
  | 'waiting_confirm'
  | 'resuming'
  | 'cancelling'
  | 'cancelled'
  | 'done'
  | 'failed'
  // 长任务断线恢复（后端 task_seq 游标 + recover 契约；前端本地阶段，status 保留后端原始值）
  | 'reconnecting' // 断流自动重连中（订阅 task events）
  | 'disconnected' // 重连耗尽且对账失败（保留「重新连接」入口）
  | 'recoverable' // failed + error.recoverable（「从断点继续」）
  | 'background_running' // 对账得知任务仍在后台执行
  | 'retrying' // model_retry 事件：模型传输自动重试

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
  kind?: string
  recoverable?: boolean
  details?: unknown
}

export interface StreamState {
  taskId: string | null
  messageId: string | null
  conversationId: string | null
  segments: StreamSegment[]
  partialText: string
  toolCalls: Record<string, ToolCallCardState>
  status: string | null
  /** 标准化 UI 阶段；status 保留后端原始值以兼容既有消费者。 */
  phase: AgentRunPhase
  phaseDetail: string | null
  cancelling: boolean
  confirming: boolean
  activities: LiveRunActivity[]
  contextMetrics?: Record<string, unknown>
  interrupted: InterruptInfo | null
  error: StreamError | null
  finished: boolean
  tokenUsage?: TokenUsage
  cost?: number
  streaming: boolean
}

export interface LiveRunActivity {
  id: string
  kind: 'thinking' | 'tool' | 'responding' | 'delegating' | 'status' | 'confirmation'
  label: string
  detail?: string | null
  status: 'active' | 'done' | 'error' | 'cancelled'
  startedAt: number
  finishedAt?: number
  toolCallId?: string
}

export interface UseChatStreamOptions {
  placeholderTtlMs?: number
  /** done 事件携带最终持久化消息时回调（触发 chat store 刷新） */
  onPersistedMessage?: (message: unknown) => void
  /** 首帧携带持久化用户消息 checkpoint 锚点时回调；旧后端/恢复流可缺省 */
  onCheckpointAnchor?: (anchor: CheckpointAnchor) => void
  /** 长任务对账/事件订阅收敛到终态时通知（done → 视图层 reload 会话消息/轨迹） */
  onTaskSettled?: (info: { taskId: string; conversationId: string | null; status: TaskStatus }) => void
}

export interface UseChatStreamReturn {
  /** 当前查看会话的流式状态（切换会话经 setConversation 指向对应 entry） */
  state: ComputedRef<StreamState>
  start(req: ChatRequest): Promise<void>
  stop(): Promise<CancelTaskResult | 'unavailable'>
  /** 释放当前 shell 关联的全部会话流（工作区切换/卸载时使用） */
  stopAll(): void
  confirmInterrupt(approved: boolean, extra?: Record<string, unknown>): Promise<void>
  /** 切换当前查看的会话（不 reset，后台流继续写入各自 ctx） */
  setConversation(convId: string): void
  /** 从断点继续（仅 failed+recoverable 可用）：POST /tasks/{id}/recover 后订阅 task events */
  recover(): Promise<void>
  /** 手动重新连接（disconnected/background_running 时立即订阅 task events） */
  reconnect(): void
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
  resumeSnapshot: ResumeSnapshot | null
  resumeAccepted: boolean
  /** 已应用的最大 task_seq（跨连接游标；token 等无 task_seq 事件不推进） */
  taskCursor: number
  /** 本次断线已发起的重连尝试次数（1..3） */
  reconnectAttempts: number
  reconnectTimer: ReturnType<typeof setTimeout> | null
  /** recover POST 在途（防双击） */
  recoveryInFlight: boolean
  /** 当前是否处于任务事件订阅模式（done 收敛时触发 onTaskSettled reload） */
  eventsMode: boolean
}

/** 自动重连退避：3 次（300/600/1200ms）+ 抖动上限 */
const RECONNECT_BACKOFFS = [300, 600, 1200]
const RECONNECT_JITTER_MS = 150

interface ResumeSnapshot {
  taskId: string | null
  interrupted: InterruptInfo | null
  status: string | null
  phase: AgentRunPhase
  phaseDetail: string | null
  streaming: boolean
  confirming: boolean
  toolStatuses: Record<string, ToolCardStatus>
  activities: LiveRunActivity[]
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
    phase: 'idle',
    phaseDetail: null,
    cancelling: false,
    confirming: false,
    activities: [],
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
        resumeSnapshot: null,
        resumeAccepted: false,
        taskCursor: 0,
        reconnectAttempts: 0,
        reconnectTimer: null,
        recoveryInFlight: false,
        eventsMode: false,
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

  function finishActivities(ctx: ConvCtx, status: LiveRunActivity['status']): void {
    const now = Date.now()
    for (const activity of ctx.state.activities) {
      if (activity.status === 'active') {
        activity.status = status
        activity.finishedAt = now
      }
    }
  }

  function upsertActivity(ctx: ConvCtx, activity: Omit<LiveRunActivity, 'id'> & { id?: string }): LiveRunActivity {
    const existing = activity.toolCallId
      ? ctx.state.activities.find((a) => a.toolCallId === activity.toolCallId)
      : activity.kind === 'thinking' || activity.kind === 'responding'
        ? ctx.state.activities.find((a) => a.kind === activity.kind && a.status === 'active')
        : undefined
    if (existing) {
      Object.assign(existing, activity)
      if (activity.status === 'active') existing.finishedAt = undefined
      return existing
    }
    const created: LiveRunActivity = { ...activity, id: activity.id ?? `activity_${segId()}` }
    ctx.state.activities.push(created)
    if (ctx.state.activities.length > 50) ctx.state.activities.splice(0, ctx.state.activities.length - 50)
    return created
  }

  function markAccepted(ctx: ConvCtx): void {
    if (!ctx.resumeSnapshot) return
    ctx.resumeAccepted = true
    ctx.state.confirming = false
    ctx.resumeSnapshot = null
  }

  /** 一轮思考完成：复位本轮流式段（保留 taskId/conversationId/messageId 跨轮续用），下一轮继续 */
  function sealRound(ctx: ConvCtx): void {
    ctx.state.segments = []
    ctx.state.partialText = ''
    ctx.state.toolCalls = {}
    ctx.state.status = 'running'
    ctx.state.phase = 'running'
    ctx.state.phaseDetail = null
    finishActivities(ctx, 'done')
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
    // 取消成功后忽略已经排队的迟到帧，避免局部回复或运行态被重新写活。
    if (s.finished && s.phase === 'cancelled') return
    // task_seq 游标推进（chat/resume/events 三流统一；token 等无 task_seq 事件不推进）
    if (typeof ev.task_seq === 'number' && ev.task_seq > ctx.taskCursor) ctx.taskCursor = ev.task_seq
    // model_retry 后任一业务帧即视为恢复（各 case 会再覆写具体 phase）
    if (s.phase === 'retrying' && ev.type !== 'model_retry') s.phase = 'running'
    const p = ev.payload as Record<string, any>
    switch (ev.type) {
      case 'message_start': {
        s.taskId = p.task_id ?? s.taskId
        s.messageId = p.message_id
        s.conversationId = p.conversation_id
        s.segments = []
        s.partialText = ''
        s.status = 'running'
        s.phase = 'running'
        s.phaseDetail = null
        s.cancelling = false
        s.finished = false
        s.error = null
        s.interrupted = null
        s.streaming = true
        s.confirming = false
        if (
          typeof p.conversation_id === 'string' && p.conversation_id &&
          typeof p.user_message_id === 'string' && p.user_message_id &&
          typeof p.checkpoint_id === 'string' && p.checkpoint_id
        ) {
          opts.onCheckpointAnchor?.({
            conversationId: p.conversation_id,
            userMessageId: p.user_message_id,
            checkpointId: p.checkpoint_id,
          })
        }
        upsertActivity(ctx, { kind: 'status', label: '开始执行', status: 'active', startedAt: Date.now() })
        break
      }
      case 'token': {
        if (ctx.resumeSnapshot) markAccepted(ctx)
        ctx.pendingText += (p.text ?? '') as string
        s.phase = 'responding'
        s.phaseDetail = null
        upsertActivity(ctx, { kind: 'responding', label: '生成回复', status: 'active', startedAt: Date.now() })
        ctx.flush()
        break
      }
      case 'tool_call': {
        if (ctx.resumeSnapshot) markAccepted(ctx)
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
        s.phase = 'tool'
        s.phaseDetail = card.tool_name
        upsertActivity(ctx, {
          kind: 'tool', label: card.status === 'awaiting_confirm' ? '等待确认' : '执行工具', detail: card.tool_name,
          status: card.status === 'awaiting_confirm' ? 'active' : 'active', startedAt: card.startedAt, toolCallId: card.tool_call_id,
        })
        break
      }
      case 'tool_result': {
        if (ctx.resumeSnapshot) markAccepted(ctx)
        handleToolResult(p as ToolResultPayload, ctx)
        const card = findCard(p, ctx)
        if (card) upsertActivity(ctx, {
          kind: 'tool', label: card.status === 'error' ? '工具失败' : card.status === 'done' ? '工具完成' : '执行工具',
          detail: card.tool_name, status: card.status === 'error' ? 'error' : card.status === 'done' ? 'done' : 'active',
          startedAt: card.startedAt, finishedAt: card.status === 'done' || card.status === 'error' ? Date.now() : undefined,
          toolCallId: card.tool_call_id,
        })
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
        s.phase = 'waiting_confirm'
        s.phaseDetail = null
        s.cancelling = false
        s.streaming = false
        s.confirming = false
        upsertActivity(ctx, { kind: 'confirmation', label: '等待确认', status: 'active', startedAt: Date.now() })
        break
      }
      case 'status': {
        s.status = (p.status as string) ?? s.status
        s.contextMetrics = p.context_metrics
        if (p.accepted === true && ctx.resumeSnapshot) {
          markAccepted(ctx)
        }
        if (s.status === 'finalizing') {
          s.phase = 'finalizing'
          s.phaseDetail = null
          upsertActivity(ctx, { kind: 'status', label: '整理回复', status: 'active', startedAt: Date.now() })
        } else if (s.status === 'waiting_confirm') {
          s.phase = 'waiting_confirm'
          s.phaseDetail = null
          upsertActivity(ctx, { kind: 'confirmation', label: '等待确认', status: 'active', startedAt: Date.now() })
        } else if (s.status === 'cancelled') {
          s.phase = 'cancelled'
          s.phaseDetail = null
          s.finished = true
          s.streaming = false
          s.cancelling = false
          finishActivities(ctx, 'cancelled')
        } else if (s.status === 'failed') {
          s.phase = 'failed'
          s.phaseDetail = null
          s.finished = true
          s.streaming = false
          s.cancelling = false
          finishActivities(ctx, 'error')
        } else if (s.streaming) {
          s.phase = (p.phase as AgentRunPhase) || 'running'
          s.phaseDetail = p.detail ?? null
        }
        if (p.accepted === true && p.phase === 'tool') {
          s.phase = 'tool'
          s.phaseDetail = p.detail ?? null
          upsertActivity(ctx, { kind: 'tool', label: '执行工具', detail: p.detail ?? null, status: 'active', startedAt: Date.now(), toolCallId: p.tool_call_id })
        } else if (s.streaming && p.phase === 'tool') {
          upsertActivity(ctx, { kind: 'tool', label: '执行工具', detail: p.detail ?? null, status: 'active', startedAt: Date.now(), toolCallId: p.tool_call_id })
        }
        break
      }
      case 'agent_switch': {
        if (ctx.resumeSnapshot) markAccepted(ctx)
        // 多 Agent 切换（docs/03 §3.3）：以独立段混排进事件序（文本/工具/切换按序）
        const { from_agent: from, to_agent: to, reason } = p as AgentSwitchPayload
        s.segments.push({ kind: 'agent', id: segId(), from, to, reason })
        s.phase = 'delegating'
        s.phaseDetail = to
        upsertActivity(ctx, { kind: 'delegating', label: '切换协作者', detail: to, status: 'active', startedAt: Date.now() })
        break
      }
      case 'thinking': {
        if (ctx.resumeSnapshot) markAccepted(ctx)
        // 思考（docs/03 §3.3）：一轮思考累积到末段，不因分块堆叠多行
        const t = (p.text ?? '') as string
        const last = s.segments[s.segments.length - 1]
        if (last && last.kind === 'thinking') last.text += t
        else s.segments.push({ kind: 'thinking', id: segId(), text: t })
        s.phase = 'thinking'
        s.phaseDetail = null
        upsertActivity(ctx, { kind: 'thinking', label: '思考中', status: 'active', startedAt: Date.now() })
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
        if (ctx.resumeSnapshot) markAccepted(ctx)
        flushText(ctx)
        flushNow()
        const done = p as DonePayload
        s.tokenUsage = done.token_usage
        s.cost = done.cost
        s.finished = true
        s.streaming = false
        s.status = 'done'
        s.phase = 'done'
        s.phaseDetail = null
        s.cancelling = false
        s.confirming = false
        finishActivities(ctx, 'done')
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
        // 事件订阅模式（断线重连/recover）的 done → 通知视图层 reload 会话消息/轨迹
        if (ctx.eventsMode) {
          opts.onTaskSettled?.({ taskId: s.taskId ?? '', conversationId: s.conversationId, status: 'done' })
        }
        break
      }
      case 'error': {
        if (ctx.resumeSnapshot) markAccepted(ctx)
        flushNow()
        s.error = { code: p.code, message: p.message, retryable: p.retryable, kind: p.kind, recoverable: p.recoverable, details: p.details }
        s.finished = true
        s.streaming = false
        s.status = 'failed'
        // recoverable 事件不显示普通失败态——错误条展示「从断点继续」
        s.phase = p.recoverable === true ? 'recoverable' : 'failed'
        s.phaseDetail = null
        s.cancelling = false
        s.confirming = false
        finishActivities(ctx, 'error')
        break
      }
      case 'model_retry': {
        // 模型传输断线自动重试（后端自动仅重试一次）：只清未封口 partialText/thinking 段，保留已持久化 tool/agent 段
        const rp = p as ModelRetryPayload
        if (rp.reset_partial === true) {
          ctx.pendingText = ''
          s.partialText = ''
          s.segments = s.segments.filter((seg) => seg.kind === 'tool' || seg.kind === 'agent')
        }
        s.phase = 'retrying'
        s.streaming = true
        s.phaseDetail = `（${rp.attempt}/${rp.max_attempts}）`
        upsertActivity(ctx, {
          kind: 'status',
          label: '模型连接中断，正在从最近断点重试',
          detail: s.phaseDetail,
          status: 'active',
          startedAt: Date.now(),
        })
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
    // 断流（网络/流中断）且已有 task_id → 进入自动重连链：不标记业务 failed、不重发原消息。
    // finished 的任务忽略迟到的传输错误（数据已收敛，错误帧可能是连接收尾时的竞态）。
    if (e.name === 'SseTransportError' && ctx.state.taskId && !ctx.state.finished) {
      enterReconnecting(ctx)
      return
    }
    ctx.state.error = {
      code: e.name === 'SseRequestError' ? (e as { code?: number }).code ?? 50001 : 50001,
      message: e.message,
      retryable: true,
    }
    ctx.state.finished = true
    ctx.state.streaming = false
    ctx.state.status = 'failed'
    ctx.state.phase = 'failed'
    ctx.state.phaseDetail = null
    ctx.state.cancelling = false
    ctx.state.confirming = false
    finishActivities(ctx, 'error')
  }

  /** chat 流干净 EOF（无 done/error）：半截 body。已有 task_id 时同样进入重连链，等待任务终态。 */
  function onChatClose(ctx: ConvCtx): void {
    const s = ctx.state
    if (s.finished || s.phase === 'cancelled' || s.phase === 'waiting_confirm'
      || s.phase === 'recoverable' || s.phase === 'reconnecting') return
    if (s.taskId) enterReconnecting(ctx)
  }

  /* ---------- 断线自动重连（长任务断线恢复契约） ---------- */

  function enterReconnecting(ctx: ConvCtx, opts: { immediate?: boolean } = {}): void {
    if (ctx.state.phase === 'reconnecting' && !opts.immediate) return
    if (ctx.reconnectTimer) {
      clearTimeout(ctx.reconnectTimer)
      ctx.reconnectTimer = null
    }
    const s = ctx.state
    s.phase = 'reconnecting'
    s.phaseDetail = null
    s.streaming = true
    s.error = null
    if (opts.immediate) {
      ctx.reconnectAttempts = 0
      void subscribeTaskEvents(ctx)
    } else {
      scheduleReconnect(ctx)
    }
  }

  function scheduleReconnect(ctx: ConvCtx): void {
    if (ctx.reconnectTimer) return
    const attempt = ctx.reconnectAttempts + 1
    ctx.reconnectAttempts = attempt
    if (attempt > RECONNECT_BACKOFFS.length) {
      // 3 次退避耗尽 → 终局对账（按任务状态收敛；对账失败才 disconnected）
      void reconcileTask(ctx)
      return
    }
    const jitter = Math.floor(Math.random() * RECONNECT_JITTER_MS)
    ctx.reconnectTimer = setTimeout(() => {
      ctx.reconnectTimer = null
      void subscribeTaskEvents(ctx)
    }, RECONNECT_BACKOFFS[attempt - 1] + jitter)
  }

  /** 订阅任务事件：先补发 task_seq > cursor 的持久化边界事件，再 live-tail */
  async function subscribeTaskEvents(ctx: ConvCtx): Promise<void> {
    const taskId = ctx.state.taskId
    if (!taskId) return
    ctx.eventsMode = true
    const controller = new AbortController()
    ctx.controller = controller
    await streamTaskEvents(
      taskId,
      { afterSeq: ctx.taskCursor > 0 ? ctx.taskCursor : undefined, signal: controller.signal },
      {
        onEvent: (ev) => {
          if (acceptTaskEvent(ev, ctx)) applyEvent(ev, ctx)
        },
        onError: (e) => onEventsError(e, ctx),
        onClose: () => onEventsClose(ctx),
      },
    )
    if (ctx.controller === controller) ctx.controller = null
  }

  /** task_seq 跨连接去重：<= cursor 丢弃；> cursor 应用并推进；无 task_seq（token 等）只当前连接消费 */
  function acceptTaskEvent(ev: SseEnvelope, ctx: ConvCtx): boolean {
    const ts = ev.task_seq
    if (typeof ts === 'number') {
      if (ts <= ctx.taskCursor) return false
      ctx.taskCursor = ts
      // 一次成功连接（首个事件到达）= 本次断线周期结束，下次断线重新计退避
      ctx.reconnectAttempts = 0
    }
    return true
  }

  function onEventsError(e: Error, ctx: ConvCtx): void {
    if (e.name === 'AbortError' || ctx.controller?.signal.aborted) return
    // 旧后端无 events 端点（404/REST 拒绝）→ 一次对账收敛，不重试风暴
    if (e.name === 'SseRequestError') {
      void reconcileTask(ctx)
      return
    }
    if (ctx.reconnectAttempts >= RECONNECT_BACKOFFS.length) void reconcileTask(ctx)
    else scheduleReconnect(ctx)
  }

  function onEventsClose(ctx: ConvCtx): void {
    const s = ctx.state
    if (s.finished || s.phase === 'cancelled' || s.phase === 'reconnecting' || s.phase === 'recoverable') return
    if (ctx.reconnectAttempts >= RECONNECT_BACKOFFS.length) void reconcileTask(ctx)
    else scheduleReconnect(ctx)
  }

  /** 终局对账：GET /tasks/{id} 按状态收敛；对账本身失败 → disconnected */
  async function reconcileTask(ctx: ConvCtx): Promise<void> {
    const taskId = ctx.state.taskId
    if (!taskId) return
    let task: Task
    try {
      task = await getTaskStatus(taskId)
    } catch {
      enterDisconnected(ctx)
      return
    }
    // 用服务端水位补齐游标（供后续订阅/recover）
    if (typeof task.last_event_seq === 'number' && task.last_event_seq > ctx.taskCursor) {
      ctx.taskCursor = task.last_event_seq
    }
    const s = ctx.state
    s.streaming = false
    switch (task.status) {
      case 'running':
      case 'pending':
        s.status = task.status
        s.phase = 'background_running'
        s.phaseDetail = null
        upsertActivity(ctx, { kind: 'status', label: '任务仍在后台执行', status: 'active', startedAt: Date.now() })
        break
      case 'waiting_confirm': {
        const pc = (task.pending_confirm ?? {}) as Record<string, unknown>
        s.interrupted = {
          node_id: typeof pc.node_id === 'string' ? pc.node_id : 'node_tool',
          payload: pc,
          confirm_required: true,
          task_id: taskId,
        }
        for (const card of Object.values(s.toolCalls)) {
          if (card.status === 'running' || card.status === 'pending') card.status = 'awaiting_confirm'
        }
        s.status = 'waiting_confirm'
        s.phase = 'waiting_confirm'
        s.phaseDetail = null
        s.confirming = false
        s.finished = false
        upsertActivity(ctx, { kind: 'confirmation', label: '等待确认', status: 'active', startedAt: Date.now() })
        break // 视图层 watch interrupted → 弹窗自动恢复，confirmInterrupt 复用既有链路
      }
      case 'done':
        s.status = 'done'
        s.phase = 'done'
        s.phaseDetail = null
        s.finished = true
        finishActivities(ctx, 'done')
        opts.onTaskSettled?.({ taskId, conversationId: s.conversationId, status: 'done' })
        break
      case 'failed': {
        const err = task.error
        const recoverable = typeof err === 'object' && err !== null && (err as TaskError).recoverable === true
        s.status = 'failed'
        s.error = taskErrorToStreamError(err)
        s.finished = true
        s.cancelling = false
        s.confirming = false
        s.phase = recoverable ? 'recoverable' : 'failed'
        s.phaseDetail = null
        finishActivities(ctx, 'error')
        break
      }
      case 'cancelled':
        s.status = 'cancelled'
        s.phase = 'cancelled'
        s.phaseDetail = null
        s.finished = true
        s.cancelling = false
        finishActivities(ctx, 'cancelled')
        break
    }
  }

  function enterDisconnected(ctx: ConvCtx): void {
    const s = ctx.state
    s.phase = 'disconnected'
    s.phaseDetail = null
    s.streaming = false
    upsertActivity(ctx, { kind: 'status', label: '连接已断开', status: 'error', startedAt: Date.now(), finishedAt: Date.now() })
  }

  function taskErrorToStreamError(err: Task['error']): StreamError {
    if (err == null || typeof err === 'string') {
      return { code: 50001, message: typeof err === 'string' ? err : '任务执行失败', retryable: true }
    }
    return {
      code: err.code ?? 50001,
      message: err.message ?? '任务执行失败',
      retryable: err.retryable,
      kind: err.kind,
      recoverable: err.recoverable,
      details: err.details,
    }
  }

  /** 从断点继续：recover POST 成功后订阅事件，任务续跑事件自然推进 */
  async function recover(): Promise<void> {
    const ctx = currentCtx()
    const taskId = ctx.state.taskId
    if (!taskId || ctx.state.phase !== 'recoverable' || ctx.recoveryInFlight) return
    ctx.recoveryInFlight = true
    const s = ctx.state
    try {
      await recoverTask(taskId)
      s.status = 'running'
      s.finished = false
      s.error = null
      enterReconnecting(ctx, { immediate: true })
    } catch (e) {
      s.error = {
        code: (e as { code?: number }).code ?? 50001,
        message: e instanceof Error ? e.message : '恢复失败',
        retryable: true,
      }
      s.phase = 'recoverable'
    } finally {
      ctx.recoveryInFlight = false
    }
  }

  /** 手动重新连接：立即订阅 task events（退避清零） */
  function reconnect(): void {
    const ctx = currentCtx()
    const taskId = ctx.state.taskId
    if (!taskId) return
    if (ctx.state.phase !== 'disconnected' && ctx.state.phase !== 'background_running') return
    enterReconnecting(ctx, { immediate: true })
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
    s.phase = 'idle'
    s.phaseDetail = null
    s.cancelling = false
    s.confirming = false
    s.activities = []
    s.interrupted = null
    s.error = null
    s.finished = false
    s.streaming = false
    ctx.pendingText = ''
    clearTimers(ctx)
    ctx.resumeSnapshot = null
    ctx.resumeAccepted = false
    ctx.controller?.abort()
    ctx.controller = null
    if (ctx.reconnectTimer) {
      clearTimeout(ctx.reconnectTimer)
      ctx.reconnectTimer = null
    }
    ctx.reconnectAttempts = 0
    ctx.taskCursor = 0
    ctx.recoveryInFlight = false
    ctx.eventsMode = false
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
    ctx.state.phase = 'starting'
    ctx.state.phaseDetail = null
    ctx.state.status = 'pending'
    const controller = new AbortController()
    ctx.controller = controller
    try {
      await streamChatAt(
        '/api/v1/chat/stream',
        req,
        { onEvent: (ev) => applyEvent(ev, ctx), onError: (e) => onError(e, ctx), onClose: () => onChatClose(ctx) },
        controller.signal,
      )
    } finally {
      // 静默关流（无 done/error）兜底：避免 streaming 卡 true 导致输入框永久禁用。
      // 断线重连/retry/后台执行期不得复位 streaming，且不得清掉 events 订阅的 controller。
      if (ctx.controller === controller) ctx.controller = null
      if (!ctx.state.finished && !['reconnecting', 'retrying', 'background_running'].includes(ctx.state.phase)) {
        ctx.state.streaming = false
      }
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
    const interrupted = ctx.state.interrupted
    const toolStatuses: Record<string, ToolCardStatus> = {}
    for (const [id, card] of Object.entries(ctx.state.toolCalls)) toolStatuses[id] = card.status
    ctx.resumeSnapshot = {
      taskId: ctx.state.taskId,
      interrupted,
      status: ctx.state.status,
      phase: ctx.state.phase,
      phaseDetail: ctx.state.phaseDetail,
      streaming: ctx.state.streaming,
      confirming: ctx.state.confirming,
      toolStatuses,
      activities: ctx.state.activities.map((a) => ({ ...a })),
    }
    ctx.resumeAccepted = false
    const pendingCard = Object.values(ctx.state.toolCalls).find((card) => card.status === 'awaiting_confirm')
    const toolName = pendingCard?.tool_name ?? '工具'
    ctx.state.interrupted = null
    ctx.state.status = approved ? 'running' : 'cancelling'
    ctx.state.phase = approved ? 'resuming' : 'cancelling'
    ctx.state.phaseDetail = approved ? toolName : null
    ctx.state.confirming = true
    ctx.state.streaming = true
    if (pendingCard) pendingCard.status = approved ? 'running' : 'cancelled'
    upsertActivity(ctx, {
      kind: 'confirmation',
      label: approved ? `已确认，正在继续执行 ${toolName}` : '已拒绝，正在停止执行',
      detail: approved ? toolName : null,
      status: 'active',
      startedAt: Date.now(),
      toolCallId: pendingCard?.tool_call_id,
    })
    ctx.controller = new AbortController()
    const resumeController = ctx.controller
    let resumeError: Error | null = null
    try {
      await streamTaskResume(
        taskId,
        { approved, ...extra },
        {
          onEvent: (ev) => applyEvent(ev, ctx),
          onError: (e) => { resumeError = e },
        },
        resumeController.signal,
      )
      const err = resumeError as Error | null
      if (err && !ctx.resumeAccepted) {
        if (typeof (err as { status?: unknown }).status === 'number') {
          rollbackResume(ctx, err)
        } else {
          await reconcileResume(ctx, err)
        }
      }
    } finally {
      // 同上：静默关流兜底。断线重连/retry/后台执行期不得复位 streaming；只清自己的 controller（重连订阅另有 controller）
      if (ctx.controller === resumeController) ctx.controller = null
      if (!ctx.state.finished && !ctx.state.confirming
        && !['reconnecting', 'retrying', 'background_running'].includes(ctx.state.phase)) {
        ctx.state.streaming = false
      }
    }
  }

  function rollbackResume(ctx: ConvCtx, error: Error): void {
    const snapshot = ctx.resumeSnapshot
    if (!snapshot) return
    ctx.state.taskId = snapshot.taskId
    ctx.state.interrupted = snapshot.interrupted
    ctx.state.status = snapshot.status
    ctx.state.phase = snapshot.phase
    ctx.state.phaseDetail = snapshot.phaseDetail
    ctx.state.streaming = snapshot.streaming
    ctx.state.confirming = false
    for (const [id, status] of Object.entries(snapshot.toolStatuses)) {
      const card = ctx.state.toolCalls[id]
      if (card) card.status = status
    }
    ctx.state.activities = snapshot.activities.map((a) => ({ ...a }))
    upsertActivity(ctx, { kind: 'confirmation', label: '继续执行失败，可重试', status: 'error', startedAt: Date.now(), finishedAt: Date.now() })
    ctx.state.error = { code: (error as { code?: number }).code ?? 50001, message: error.message, retryable: true }
    ctx.resumeSnapshot = null
    ctx.resumeAccepted = false
  }

  async function reconcileResume(ctx: ConvCtx, error: Error): Promise<void> {
    const taskId = ctx.state.taskId
    if (!taskId) return rollbackResume(ctx, error)
    try {
      const task = await getTaskStatus(taskId)
      if (task.status === 'waiting_confirm') return rollbackResume(ctx, error)
      ctx.state.confirming = false
      ctx.resumeSnapshot = null
      ctx.resumeAccepted = true
      if (task.status === 'running' || task.status === 'pending') {
        // 任务确认在跑 → 升级为真实 events 订阅（能收敛到 done → reload），不再静态展示「执行中（连接已中断）」
        enterReconnecting(ctx, { immediate: true })
        return
      }
      ctx.state.streaming = false
      ctx.state.finished = true
      ctx.state.status = task.status
      ctx.state.phase = task.status === 'done' ? 'done' : task.status === 'cancelled' ? 'cancelled' : 'failed'
      finishActivities(ctx, task.status === 'done' ? 'done' : task.status === 'cancelled' ? 'cancelled' : 'error')
    } catch {
      rollbackResume(ctx, error)
    }
  }

  function markCancelled(ctx: ConvCtx): void {
    flushText(ctx)
    flushNow()
    ctx.controller?.abort()
    clearTimers(ctx)
    if (ctx.reconnectTimer) {
      clearTimeout(ctx.reconnectTimer)
      ctx.reconnectTimer = null
    }
    ctx.reconnectAttempts = 0
    for (const card of Object.values(ctx.state.toolCalls)) {
      if (card.status === 'pending' || card.status === 'running' || card.status === 'awaiting_confirm') card.status = 'cancelled'
    }
    ctx.state.interrupted = null
    ctx.state.streaming = false
    ctx.state.finished = true
    ctx.state.status = 'cancelled'
    ctx.state.phase = 'cancelled'
    ctx.state.phaseDetail = null
    ctx.state.cancelling = false
    ctx.state.confirming = false
  }

  async function stop(): Promise<CancelTaskResult | 'unavailable'> {
    const ctx = currentCtx()
    if (!ctx.state.streaming || ctx.state.cancelling) return 'unavailable'
    const taskId = ctx.state.taskId
    if (!taskId) {
      // 兼容尚未升级的后端：只能停止当前 SSE，明确由调用方提示“后端仍可能继续运行”。
      markCancelled(ctx)
      return 'unavailable'
    }
    const previousPhase = ctx.state.phase
    ctx.state.cancelling = true
    ctx.state.phase = 'cancelling'
    ctx.state.phaseDetail = null
    let result: CancelTaskResult
    try {
      result = await cancelTask(taskId)
    } catch (e) {
      ctx.state.cancelling = false
      ctx.state.phase = previousPhase
      throw e
    }
    if (result === 'already-finished') {
      ctx.state.cancelling = false
      return result
    }
    markCancelled(ctx)
    return result
  }

  function stopAll(): void {
    for (const ctx of convCtxs.values()) {
      flushText(ctx)
      ctx.controller?.abort()
      clearTimers(ctx)
      if (ctx.reconnectTimer) {
        clearTimeout(ctx.reconnectTimer)
        ctx.reconnectTimer = null
      }
      ctx.state.streaming = false
      ctx.state.finished = true
      ctx.state.phase = 'idle'
      ctx.state.phaseDetail = null
      ctx.state.cancelling = false
      ctx.state.interrupted = null
      ctx.state.confirming = false
      ctx.resumeSnapshot = null
      ctx.resumeAccepted = false
      ctx.reconnectAttempts = 0
      ctx.recoveryInFlight = false
      ctx.eventsMode = false
      finishActivities(ctx, 'cancelled')
    }
    flushNow()
  }

  const state = computed<StreamState>(() => currentState.value)

  return { state, start, stop, stopAll, confirmInterrupt, setConversation, recover, reconnect }
}
