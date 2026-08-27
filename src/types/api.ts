/** REST 契约类型（对齐 docs/03 §2/§5、docs/04 §3，字段 snake_case） */
import type {
  AttachmentStatus,
  KbDocumentStatus,
  LogLevel,
  MessageRole,
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
  /** 工作区文件引用（docs/03 §5.2：相对 root_path，后端读内容注入上下文，带来源标记 + 大小上限） */
  file_refs?: FileRef[]
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
  /** 工作区会话（M7-B，docs/03 §5.2）；null/缺省 = 普通对话 */
  workspace_id?: string
  last_message_at?: string
  created_at: string
}

export interface ChatMessageInput {
  content: string
  role: 'user'
  attachments?: string[]
  /** 工作区文件引用（docs/03 §5.2：相对 root_path，后端读内容注入上下文） */
  file_refs?: FileRef[]
}

export interface ChatRequest {
  conversation_id: string | null
  workspace_id?: string | null
  message: ChatMessageInput
  stream: true
}

export interface CreateConversationRequest {
  title: string
  /** 工作区会话（M7-B）：null/缺省 = 普通对话 */
  workspace_id?: string
}

/** ---------- 工作区（M7-B，docs/03 §5.14 / docs/04 §3.11 / 交接板 2026-08-20） ---------- */
export interface FileRef {
  /** 相对 root_path 的文件路径（服务端强制 realpath 校验，防越权） */
  path: string
}

export interface Workspace {
  id: string
  org_id?: string
  name: string
  description?: string
  /** 本地文件夹绝对路径（后端托管，前端不可指定） */
  root_path?: string
  /** 工作区级指令（经消息通道 [工作区] 块注入 project_overlay，绝不进 system_prompt） */
  project_instructions?: string
  status: 'active' | 'archived'
  created_by?: string
  created_at: string
}

/** 文件树节点（一层；path 相对 root，父路径 = 去掉末段） */
export interface WorkspaceFile {
  name: string
  path: string
  is_dir: boolean
  size?: number
}

export interface CreateWorkspaceRequest {
  name: string
  description?: string
  project_instructions?: string
}

export interface UpdateWorkspaceRequest {
  name?: string
  description?: string
  project_instructions?: string
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

/** ---------- Skills（M7-A 简化 2026-08-25：两级文件目录，删 org CRUD / git 导入） ---------- */
export interface Skill {
  name: string
  /** 路由描述（进 project_overlay 消息通道，主 Agent 据此判断何时使用） */
  description: string
  /** 相对 skills 根的路径（全局 skills/<name>/SKILL.md；工作区 .agent/skills/<name>/SKILL.md） */
  path: string
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
export interface LongTermMemory {
  id: string
  card_type: 'json_card' | 'note'
  title: string
  body: unknown
  tags?: string[]
  importance?: number
  workspace_id?: string | null
  created_at: string
  updated_at?: string
}

/** 项目记忆文件索引（P5：工作区 .agent/memory/*.md，正文按需 readWorkspaceFile） */
export interface ProjectMemoryFile {
  path: string
  name: string
  title: string
  type: string
  tags: string[]
  created_at?: string
  updated_at?: string
  summary: string
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
  importance?: number
  workspace_id?: string
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

/** ---------- Provider 配置（前端定义契约 docs/03 §5.6，后端已实现 08-17） ---------- */
export interface ProviderConfig {
  id: string
  /** 配置别名（自由文本，非厂商名） */
  name: string
  /** 官网链接（可选，纯展示） */
  website?: string | null
  /** 请求地址（base 或完整 URL，见 is_full_url） */
  base_url?: string | null
  /** 请求地址是否完整 URL（含 /chat/completions）；false = base，系统自动拼接 */
  is_full_url?: boolean
  /** 模型名（裸名，如 gpt-4o / deepseek-chat） */
  model?: string | null
  enabled: boolean
  /** api_key 是否已配置（后端不回传明文） */
  has_key: boolean
  created_at?: string
}

export interface SaveProviderRequest {
  name: string
  website?: string | null
  base_url?: string | null
  is_full_url?: boolean
  api_key?: string
  model?: string | null
  enabled?: boolean
}
