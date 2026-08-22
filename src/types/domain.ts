/** 领域枚举与常量（对齐 docs/03 §2.3、docs/04 §3） */

export type TaskStatus = 'pending' | 'running' | 'waiting_confirm' | 'cancelled' | 'done' | 'failed'

export type ToolType = 'perception' | 'execution' | 'collaboration' | 'user_comms' | 'event' | 'agent_control'

export type AttachmentStatus = 'uploaded' | 'analyzing' | 'ready' | 'failed'

export type MessageRole = 'system' | 'user' | 'assistant' | 'tool'

export type KbDocumentStatus = 'uploaded' | 'chunking' | 'indexing' | 'indexed' | 'failed' | 'archived'

export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'

/** token 用量（docs/04 message.token_usage） */
export interface TokenUsage {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  prefix_cache_hit_tokens?: number
}

/** 输入上限：message.content 32K 字符（超限 → 40014 输入超长） */
export const TOKEN_LIMIT = 32000

/** 附件上传约束（docs/03 §5.9） */
export const UPLOAD_MAX_BYTES = 20 * 1024 * 1024
export const UPLOAD_MAX_PER_MESSAGE = 10
