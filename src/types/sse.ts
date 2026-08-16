/** SSE 事件协议（docs/03 §3） */
import type { TokenUsage } from './domain'

export type SseEventType =
  | 'message_start'
  | 'token'
  | 'tool_call'
  | 'tool_result'
  | 'agent_switch'
  | 'status'
  | 'interrupt'
  | 'done'
  | 'error'
  // 监视器预留（docs/03 §3.3，MVP 后实施）
  | 'thinking'
  | 'run_progress'
  | 'tool_exec'
  // 通知流（docs/03 §5.11 notifications/stream；事件类型契约未定，mock 用此）
  | 'notification'

/** 统一事件信封 */
export interface SseEnvelope<T = unknown> {
  id: string
  seq: number
  type: SseEventType
  ts: number
  payload: T
}

export interface MessageStartPayload {
  message_id: string
  agent_id: string
  conversation_id: string
  /** 任务 id（真实契约未含，mock 提供；前端兜底用 conversation_id） */
  task_id?: string
}

export interface TokenPayload {
  text: string
}

export interface ToolCallPayload {
  tool_call_id: string
  tool_name: string
  input: unknown
  require_confirm?: boolean
}

export interface ToolResultPayload {
  tool_call_id: string
  tool_name: string
  ok: boolean
  summary?: string
  structured?: unknown
  /** 占位/回填语义（docs/03 §3.5） */
  placeholder?: boolean
  job_ref?: string
  error?: string
  duration_ms?: number
}

export interface AgentSwitchPayload {
  from_agent: string
  to_agent: string
  reason?: string
}

export interface StatusPayload {
  status: string
  context_metrics?: Record<string, unknown>
}

export interface InterruptPayload {
  node_id: string
  payload?: unknown
  confirm_required?: boolean
  task_id?: string
}

export interface DonePayload {
  message_id: string
  token_usage?: TokenUsage
  cost?: number
  message?: unknown
}

export interface ErrorPayload {
  code: number
  message: string
  retryable?: boolean
}

export interface ThinkingPayload {
  text: string
  ts: number
  token_usage?: TokenUsage
}

export interface RunProgressPayload {
  stage: string
  progress?: number
  context_metrics?: Record<string, unknown>
}

export interface ToolExecPayload {
  tool_name: string
  input?: unknown
  output?: unknown
  duration_ms?: number
  ok?: boolean
}
