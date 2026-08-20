/** REST 契约类型（对齐 docs/03 §2/§5、docs/04 §3，字段 snake_case） */
import type {
  AttachmentStatus,
  CandidateChangeType,
  CandidateStatus,
  KbDocumentStatus,
  LogLevel,
  MessageRole,
  Role,
  TaskStatus,
  ToolType,
  TokenUsage,
} from './domain'

/** 统一响应信封 */
export interface ApiEnvelope<T = unknown> {
  code: number
  message: string
  data: T
  trace_id?: string
}

/** 分页响应 data */
export interface Paged<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** ---------- 认证 / 用户 ---------- */
export interface User {
  id: string
  name: string
  username?: string
  role: Role
  org_id?: string
  org_name?: string
  enabled?: boolean
  created_at?: string
}

export interface LoginResponse {
  token: string
  user: User
}

export interface LoginRequest {
  username: string
  password: string
}

export interface CreateUserRequest {
  username: string
  password: string
  name: string
  role: Role
  org_id?: string
}

/** ---------- 对话 / 消息 ---------- */
export interface ToolCallRecord {
  tool_call_id: string
  tool_name: string
  input: unknown
  output?: unknown
  status?: string
  /** 事件序（供文本×工具卡混排，docs/04 message.tool_calls） */
  position: number
  duration_ms?: number
}

export interface Message {
  id: string
  conversation_id: string
  role: MessageRole
  content: string
  attachments?: AttachmentRef[]
  tool_calls?: ToolCallRecord[]
  token_usage?: TokenUsage
  /** 单条消息成本（¥；契约扩展提案：逐轮 cost 后端 emit/持久化后可用，mock 演示） */
  cost?: number
  trace_id?: string
  /** 轮次序号（逐轮消息：一轮思考 = 一条消息；同一 turn 内排序用） */
  round?: number
  /** 推理链（docs/03 §3.3；后端持久化后返回，前端活动区折叠显示） */
  thinking?: string
  created_at: string
}

/** ---------- 对话轨迹（Trajectory，docs/03 §5.2.x）：按会话隔离、只读派生 ---------- */
export interface TrajectoryToolCall {
  tool_call_id: string
  tool_name: string
  input: unknown
  output?: unknown
  ok?: boolean
  duration_ms?: number
  position: number
}

export type TrajectoryNodeKind = 'user' | 'assistant' | 'context' | 'steering' | 'compaction'

export interface TrajectoryNode {
  /** 全局序号（按 seq 排序） */
  seq: number
  kind: TrajectoryNodeKind
  /** epoch ms（消息 created_at） */
  time: number
  content?: string
  /** assistant 推理（thinking 事件落库，可空） */
  thinking?: string
  /** context/system 更新的前后差异（供 Diff 标签） */
  diff?: { before: string; after: string }
  token_usage?: TokenUsage
  trace_id?: string
  tool_calls?: TrajectoryToolCall[]
}

export interface TrajectoryDetail {
  conversation_id: string
  nodes: TrajectoryNode[]
  /** 还有更早历史（分页加载，docs/03 §5.2.1） */
  has_more?: boolean
}

export interface AttachmentRef {
  attachment_id: string
  mime_type?: string
  name?: string
  size?: number
  status?: AttachmentStatus
}

export interface Conversation {
  id: string
  user_id: string
  agent_id: string
  title: string
  status: string
  max_messages?: number
  last_message_at?: string
  created_at: string
}

export interface ChatMessageInput {
  content: string
  role: 'user'
  attachments?: string[]
}

export interface ChatRequest {
  conversation_id: string | null
  message: ChatMessageInput
  stream: true
}

export interface CreateConversationRequest {
  title: string
}

/** ---------- 任务 ---------- */
export interface Task {
  id: string
  agent_id: string
  status: TaskStatus
  progress?: number
  input?: unknown
  output?: unknown
  pending_confirm?: unknown
  error?: string
  created_at: string
  updated_at?: string
}

export interface SubmitTaskRequest {
  input: unknown
  params?: Record<string, unknown>
}

/** ---------- 工具 ---------- */
export interface ToolDefinition {
  id: string
  name: string
  description?: string
  params_schema?: Record<string, unknown>
  tool_type: ToolType
  enabled: boolean
  /** 平台元工具（如 tool_search/kb_search）：模型侧常驻、无需 tool_search 发现，API 序列化带出 */
  meta?: boolean
  require_confirm?: boolean
  sandbox?: 'none' | 'docker' | 'microvm'
  timeout_ms?: number
  max_concurrency?: number
  mcp_source?: string | null
  idempotent?: boolean
  created_at: string
}

export interface CreateToolRequest {
  name: string
  description?: string
  params_schema?: Record<string, unknown>
  tool_type: ToolType
  sandbox?: 'none' | 'docker' | 'microvm'
  require_confirm?: boolean
  idempotent?: boolean
}

export interface ToolTestResult {
  ok: boolean
  output?: unknown
  duration_ms?: number
  error?: string
}

export interface ToolSearchHit {
  id: string
  name: string
  description?: string
  enabled: boolean
}

export interface McpRegisterRequest {
  url_or_command: string
  headers?: Record<string, string>
  enable?: boolean
}

/** ---------- 知识库 / RAG ---------- */
export interface KbCollection {
  id: string
  name: string
  chunk_size?: number
  overlap?: number
  document_count?: number
  created_at: string
}

export interface KbDocument {
  id: string
  collection_id: string
  name: string
  mime_type?: string
  size?: number
  status: KbDocumentStatus
  chunk_count?: number
  progress?: number
  error?: string
  created_at: string
}

export interface KbDocumentStatusDetail {
  status: KbDocumentStatus
  chunk_count?: number
  progress?: number
  error?: string
}

export interface KbSearchRequest {
  collection_ids: string[]
  query: string
  top_k?: number
  hybrid?: { semantic: number; bm25: number }
}

export interface KbSearchHit {
  chunk_id: string
  text: string
  score?: number
  rerank_score?: number
}

/** ---------- 记忆 ---------- */
export interface MemoryTrace {
  id: string
  conversation_id: string
  summary: string
  created_at: string
}

export interface LongTermMemory {
  id: string
  card_type: 'json_card' | 'note'
  title: string
  body: unknown
  tags?: string[]
  importance?: number
  created_at: string
  updated_at?: string
}

export interface LongTermMemoryVersion {
  id: string
  memory_id: string
  version: number
  title: string
  body: unknown
  created_at: string
}

export interface CreateLongTermMemoryRequest {
  card_type: 'json_card' | 'note'
  title: string
  body: unknown
  tags?: string[]
}

export interface MemoryMaintenanceResult {
  summary: string
  cards_created?: number
  cards_updated?: number
}

/** ---------- 系统 / 日志 / 评估 / 成本 ---------- */
export interface SystemLog {
  id: string
  trace_id: string
  level: LogLevel
  event: string
  service?: string
  message?: string
  input?: unknown
  output?: unknown
  duration_ms?: number
  created_at: string
}

export interface TraceEvent {
  node_type: 'llm' | 'tool' | 'retrieval' | 'router'
  name: string
  status: 'success' | 'failed'
  token_usage?: TokenUsage
  duration_ms?: number
  input?: unknown
  output?: unknown
  ts: number
}

export interface TraceDetail {
  trace_id: string
  events: TraceEvent[]
}

export interface EvalSet {
  id: string
  name: string
  description?: string
  case_count?: number
  created_at: string
}

export interface EvalCase {
  id: string
  eval_set_id: string
  input: string
  expected: string
  /** L1-L5 分层（docs 06 §3.1，后端可空） */
  layer?: string
  active: boolean
}

export interface EvalRun {
  id: string
  eval_set_id: string
  /** 配对比较基线（docs 06 §2.4；无基线时为 null） */
  baseline_run_id?: string | null
  status: 'pending' | 'running' | 'done' | 'failed'
  progress?: number
  pass_rate?: number
  created_at: string
}

export interface EvalCaseResult {
  case_id: string
  input: string
  expected: string
  actual?: string
  pass: boolean
  score?: number
  latency_ms?: number
  cost?: number
}

/** ---------- 配对比较（docs 06 §2.4，McNemar 思路：真变好还是运气） ---------- */
export interface PairwiseMatrixRow {
  case_id: string
  input: string
  baseline_pass: boolean
  candidate_pass: boolean
  outcome: 'win' | 'lose' | 'tie'
}

export interface PairwiseSummary {
  baseline_pass_rate: number
  candidate_pass_rate: number
  delta: number
  wins: number
  losses: number
  ties: number
}

export interface PairwiseDetail {
  run_id: string
  baseline_run_id: string
  matrix: PairwiseMatrixRow[]
  summary: PairwiseSummary
}

export interface CostStat {
  total_cost: number
  total_calls: number
  by_provider: Array<{ provider: string; cost: number; calls: number }>
  series: Array<{ date: string; cost: number; calls: number }>
}

/** ---------- 经验候选区（M6，docs/06 §5 契约提案，前端 mock 演示，待后端认领） ---------- */
export interface Candidate {
  id: string
  title: string
  source_conversation_id?: string
  source_type: 'trajectory' | 'eval' | 'manual'
  change_type: CandidateChangeType
  status: CandidateStatus
  /** 变更契约（docs/06 §5.6）：失败证据 */
  evidence?: string
  /** 推断根因 */
  root_cause?: string
  /** 候选修改 */
  proposed_change?: string
  /** 预期修复 */
  expected_fix?: string
  /** 受损行为 */
  affected_behaviors?: string[]
  /** 验证用例 */
  validation_cases?: string[]
  created_at: string
  updated_at?: string
}

/** ---------- 附件 ---------- */
export interface UploadResponse {
  attachment_id: string
  mime_type: string
  size: number
  status: 'uploaded'
}

export interface Attachment {
  id: string
  mime_type: string
  size: number
  status: AttachmentStatus
  name?: string
  created_at: string
}

export interface AttachmentAnalysis {
  attachment_id: string
  summary?: string
  extracted_text?: string
  status: AttachmentStatus
  error?: string
}

/** ---------- 通知 ---------- */
export interface Notification {
  id: string
  title: string
  body?: string
  level: 'info' | 'success' | 'warning' | 'error'
  read: boolean
  created_at: string
}

/** ---------- Webhook（docs/03 §5.10） ---------- */
export interface WebhookConfig {
  id: string
  tool_id: string
  conversation_id?: string | null
  enabled?: boolean
  created_at?: string
}

export interface RegisterHookRequest {
  token: string
  conversation_id?: string
}

/** ---------- Provider 配置（前端定义契约，后端待实现 /settings/providers） ---------- */
export interface ProviderConfig {
  id: string
  name: string
  base_url?: string
  model?: string
  enabled: boolean
  /** api_key 是否已配置（后端不回传明文） */
  has_key: boolean
  created_at?: string
}

export interface SaveProviderRequest {
  name: string
  base_url?: string
  api_key?: string
  model?: string
  enabled?: boolean
}
