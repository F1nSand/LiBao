import { reactive } from 'vue'
import { streamChatAt, streamTaskResume } from '@/api/sse'
import type { ChatRequest, SseEnvelope, TokenUsage } from '@/types'
import type { AgentSwitchPayload, ToolResultPayload } from '@/types'
import { flushNow, throttleByRaf } from '@/utils/rAF'

/**
 * 流式消息渲染状态机（docs/02 §5.3）：
 * message_start → token* → tool_call → tool_result(占位/回填) → … → done
 * interrupt → 确认弹窗 → confirmInterrupt 续流（复用 segments/toolCalls 不回滚）
 */

export type StreamSegment =
  | { kind: 'text'; id: string; text: string }
  | { kind: 'tool'; id: string; cardId: string }
  | { kind: 'agent'; id: string; from: string; to: string; reason?: string }

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
  state: StreamState
  start(req: ChatRequest, endpoint?: string): Promise<void>
  stop(): void
  confirmInterrupt(approved: boolean, extra?: Record<string, unknown>): Promise<void>
  reset(): void
}

let uidCounter = 0
function segId(): string {
  uidCounter += 1
  return `seg_${uidCounter}`
}

export function useChatStream(opts: UseChatStreamOptions = {}): UseChatStreamReturn {
  const placeholderTtlMs = opts.placeholderTtlMs ?? 120_000

  const state = reactive<StreamState>({
    taskId: null,
    messageId: null,
    conversationId: null,
    segments: [],
    partialText: '',
    toolCalls: {},
    status: null,
    interrupted: null,
    error: null,
    finished: false,
    streaming: false,
  })

  let controller: AbortController | null = null
  let pendingText = ''
  const timers = new Map<string, ReturnType<typeof setTimeout>>()

  /** 文本追加到"唯一"文本段（始终置顶）：与持久化渲染（content 在前、tools 在后）一致，杜绝 done 后文本"跳位" */
  function flushText(): void {
    if (!pendingText) return
    const first = state.segments.find((s) => s.kind === 'text')
    if (first) {
      first.text += pendingText
    } else {
      state.segments.unshift({ kind: 'text', id: segId(), text: pendingText })
    }
    state.partialText += pendingText
    pendingText = ''
  }

  const throttledFlush = throttleByRaf(flushText)

  function clearAllTimers(): void {
    for (const t of timers.values()) clearTimeout(t)
    timers.clear()
  }

  function findCard(p: { tool_call_id?: string; job_ref?: string }): ToolCallCardState | undefined {
    if (p.tool_call_id && state.toolCalls[p.tool_call_id]) return state.toolCalls[p.tool_call_id]
    if (p.job_ref) return Object.values(state.toolCalls).find((c) => c.job_ref === p.job_ref)
    return undefined
  }

  function startPlaceholderTimer(cardId: string): void {
    const existing = timers.get(cardId)
    if (existing) clearTimeout(existing)
    timers.set(
      cardId,
      setTimeout(() => {
        const card = state.toolCalls[cardId]
        if (card && card.status === 'running') card.status = 'timeout'
      }, placeholderTtlMs),
    )
  }

  function handleToolResult(p: ToolResultPayload): void {
    const card = findCard(p)
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
      state.toolCalls[id] = c
      state.segments.push({ kind: 'tool', id: segId(), cardId: id })
      if (p.placeholder) {
        c.status = 'running'
        c.job_ref = p.job_ref
        startPlaceholderTimer(id)
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
      startPlaceholderTimer(card.tool_call_id)
      return
    }
    const t = timers.get(card.tool_call_id)
    if (t) clearTimeout(t)
    card.status = p.ok ? 'done' : 'error'
    card.summary = p.summary
    card.structured = p.structured
    card.error = p.error
    card.durationMs = p.duration_ms ?? (Date.now() - card.startedAt)
  }

  function applyEvent(ev: SseEnvelope): void {
    const p = ev.payload as Record<string, any>
    switch (ev.type) {
      case 'message_start': {
        state.taskId = p.task_id ?? state.taskId
        state.messageId = p.message_id
        state.conversationId = p.conversation_id
        state.segments = []
        state.partialText = ''
        state.status = 'running'
        state.finished = false
        state.error = null
        state.interrupted = null
        state.streaming = true
        break
      }
      case 'token': {
        pendingText += (p.text ?? '') as string
        throttledFlush()
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
        state.toolCalls[card.tool_call_id] = card
        state.segments.push({ kind: 'tool', id: segId(), cardId: card.tool_call_id })
        break
      }
      case 'tool_result': {
        handleToolResult(p as ToolResultPayload)
        break
      }
      case 'interrupt': {
        state.taskId = p.task_id ?? state.taskId
        state.interrupted = {
          node_id: p.node_id,
          payload: p.payload,
          confirm_required: p.confirm_required,
          task_id: p.task_id,
        }
        state.status = 'waiting_confirm'
        state.streaming = false
        break
      }
      case 'status': {
        state.status = (p.status as string) ?? state.status
        state.contextMetrics = p.context_metrics
        break
      }
      case 'agent_switch': {
        // 多 Agent 切换（docs/03 §3.3）：以独立段混排进事件序（文本/工具/切换按序）
        const { from_agent: from, to_agent: to, reason } = p as AgentSwitchPayload
        state.segments.push({ kind: 'agent', id: segId(), from, to, reason })
        break
      }
      case 'done': {
        flushText()
        flushNow()
        state.tokenUsage = p.token_usage
        state.cost = p.cost
        state.finished = true
        state.streaming = false
        state.status = 'done'
        opts.onPersistedMessage?.(p.message)
        break
      }
      case 'error': {
        flushNow()
        state.error = { code: p.code, message: p.message, retryable: p.retryable }
        state.finished = true
        state.streaming = false
        state.status = 'failed'
        break
      }
      default: {
        // thinking / run_progress / tool_exec：监视器预留，MVP 忽略
        break
      }
    }
  }

  function onError(e: Error): void {
    state.error = { code: 50001, message: e.message, retryable: true }
    state.finished = true
    state.streaming = false
    state.status = 'failed'
  }

  function reset(): void {
    state.taskId = null
    state.messageId = null
    state.conversationId = null
    state.segments = []
    state.partialText = ''
    state.toolCalls = {}
    state.status = null
    state.interrupted = null
    state.error = null
    state.finished = false
    state.streaming = false
    pendingText = ''
    clearAllTimers()
  }

  async function start(req: ChatRequest, endpoint?: string): Promise<void> {
    reset()
    state.streaming = true
    controller = new AbortController()
    try {
      await streamChatAt(endpoint ?? '/api/v1/chat/stream', req, { onEvent: applyEvent, onError }, controller.signal)
    } finally {
      // 静默关流（无 done/error）兜底：避免 streaming 卡 true 导致输入框永久禁用
      if (!state.finished) state.streaming = false
    }
  }

  async function confirmInterrupt(
    approved: boolean,
    extra?: Record<string, unknown>,
  ): Promise<void> {
    // fail-fast：interrupt 事件必须带 task_id，缺失即报错，不用 conversation_id 冒充（会误路由）
    const taskId = state.taskId ?? ''
    if (!taskId) {
      state.error = { code: 40001, message: '缺少 task_id，无法恢复中断', retryable: false }
      return
    }
    state.interrupted = null
    state.status = 'running'
    state.streaming = true
    controller = new AbortController()
    try {
      await streamTaskResume(taskId, { approved, ...extra }, { onEvent: applyEvent, onError }, controller.signal)
    } finally {
      // 同上：静默关流兜底
      if (!state.finished) state.streaming = false
    }
  }

  function stop(): void {
    flushText()
    flushNow()
    controller?.abort()
    clearAllTimers()
    state.streaming = false
  }

  return { state, start, stop, confirmInterrupt, reset }
}
