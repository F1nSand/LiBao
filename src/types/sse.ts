/** SSE 事件协议（docs/03 §3） */
import type { TokenUsage } from './domain'
import type { Message } from './api'

export type SseEventType =
  | 'message_start'
  | 'token'
  | 'tool_call'
  | 'tool_result'
  | 'agent_switch'
  | 'status'
  | 'interrupt'
  | 'message'
  | 'done'
  | 'error'
  // 监视器预留（docs/03 §3.3，MVP 后实施）
  | 'thinking'
  | 'run_progress'
  | 'tool_exec'
  // 通知流（docs/03 §5.11 notifications/stream；事件类型契约未定，mock 用此）
  | 'notification'
  // 模型传输断线自动重试（后端仅重试一次；长任务断线恢复契约）
  | 'model_retry'

/** 统一事件信封 */
export interface SseEnvelope<T = unknown> {
  id: string
  seq: number
  /** 跨连接单调任务事件游标（后端可选字段；旧后端缺省——缺省时只在当前连接消费，不推进游标） */
  task_seq?: number
  type: SseEventType
  ts: number
  payload: T
}

export interface MessageStartPayload {
  message_id: string
  agent_id: string
  conversation_id: string
  /** 普通聊天运行对应的可取消 Task id；兼容旧后端时仍允许缺省。 */
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
  /** resume 首帧确认字段（后端可选，旧服务保持兼容） */
  phase?: string
  detail?: string
  tool_call_id?: string
  accepted?: boolean
  message?: string
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

/** 逐轮消息封口（docs/03 §3 多消息扩展）：一轮思考（文本+工具）完成时由后端发射，前端追加为独立消息 */
export interface MessageSealPayload {
  message_id?: string
  token_usage?: TokenUsage
  /** 本轮成本（¥；契约扩展提案，后端实现前 mock 演示，前端防御式渲染） */
  cost?: number
  message: Message
}

export interface ErrorPayload {
  code: number
  message: string
  retryable?: boolean
  /** 错误类别（llm_transport / tool / validation…） */
  kind?: string
  /** 可 POST /tasks/{id}/recover 从断点继续（长任务断线恢复契约） */
  recoverable?: boolean
  details?: unknown
}

/** model_retry：模型传输自动重试（后端自动仅重试一次；手动恢复走 /tasks/{id}/recover） */
export interface ModelRetryPayload {
  attempt: number
  max_attempts: number
  /** true = 清除当前未封口 partialText/thinking 段（保留已持久化消息/工具卡） */
  reset_partial?: boolean
  reason?: string
  message?: string
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
