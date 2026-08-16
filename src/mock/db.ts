import type {
  Agent,
  AgentConfigInput,
  Conversation,
  KbCollection,
  KbDocument,
  LongTermMemory,
  MemoryTrace,
  Message,
  Notification,
  SystemLog,
  Task,
  ToolDefinition,
  User,
} from '@/types'
import { isoDate } from './util'

/** Mock 种子数据（内存态，dev 重启即重置） */

export const users: Array<User & { password: string }> = [
  { id: 'u_admin', username: 'admin', password: 'admin123', name: '管理员', role: 'admin', org_id: 'org_1', enabled: true, created_at: isoDate(60) },
  { id: 'u_dev', username: 'dev', password: 'dev123', name: '开发者', role: 'developer', org_id: 'org_1', enabled: true, created_at: isoDate(55) },
  { id: 'u_viewer', username: 'viewer', password: 'viewer123', name: '访客', role: 'viewer', org_id: 'org_1', enabled: true, created_at: isoDate(50) },
]

export const agents: Agent[] = [
  {
    id: 'ag_calc',
    name: '计算助手',
    model: 'gpt-4o',
    system_prompt: '你是计算助手，负责数学计算与推理。',
    graph_template: 'single',
    skills: ['math'],
    tools: ['tl_calculator', 'tl_time_now'],
    max_steps: 10,
    status: 'published',
    current_version: 3,
    created_at: isoDate(120),
  },
  {
    id: 'ag_search',
    name: '信息检索助手',
    model: 'gpt-4o',
    system_prompt: '你是信息检索助手，负责搜索并整理信息。',
    graph_template: 'single',
    skills: [],
    tools: ['tl_web_search', 'tl_time_now'],
    max_steps: 15,
    status: 'published',
    current_version: 2,
    created_at: isoDate(100),
  },
]

export const tools: ToolDefinition[] = [
  {
    id: 'tl_time_now',
    name: 'time_now',
    description: '获取当前时间。需要知道"现在几点"时使用，其他情况不要用。',
    params_schema: { type: 'object', properties: {}, required: [] },
    tool_type: 'perception',
    enabled: true,
    require_confirm: false,
    sandbox: 'none',
    timeout_ms: 5000,
    max_concurrency: 10,
    mcp_source: null,
    idempotent: true,
    created_at: isoDate(200),
  },
  {
    id: 'tl_calculator',
    name: 'calculator',
    description: '数学计算器，支持四则运算。涉及执行/计算结果时使用；危险或不可逆操作需确认。',
    params_schema: { type: 'object', properties: { expression: { type: 'string', description: '数学表达式' } }, required: ['expression'] },
    tool_type: 'execution',
    enabled: true,
    require_confirm: true,
    sandbox: 'none',
    timeout_ms: 5000,
    max_concurrency: 5,
    mcp_source: null,
    idempotent: false,
    created_at: isoDate(190),
  },
  {
    id: 'tl_web_search',
    name: 'web_search',
    description: '联网搜索，返回相关网页摘要。回答事实性问题前使用。',
    params_schema: { type: 'object', properties: { query: { type: 'string' }, limit: { type: 'integer', default: 5 } }, required: ['query'] },
    tool_type: 'perception',
    enabled: true,
    require_confirm: false,
    sandbox: 'docker',
    timeout_ms: 30_000,
    max_concurrency: 3,
    mcp_source: null,
    idempotent: true,
    created_at: isoDate(180),
  },
]

export const conversations: Conversation[] = [
  { id: 'c_001', user_id: 'u_admin', agent_id: 'ag_calc', title: '计算 6*7', status: 'active', max_messages: 1000, last_message_at: isoDate(10), created_at: isoDate(60) },
  { id: 'c_002', user_id: 'u_admin', agent_id: 'ag_search', title: '什么是 SSE', status: 'active', max_messages: 1000, last_message_at: isoDate(30), created_at: isoDate(90) },
  { id: 'c_long', user_id: 'u_admin', agent_id: 'ag_search', title: '长会话（轨迹分页演示）', status: 'active', max_messages: 1000, last_message_at: isoDate(20), created_at: isoDate(180) },
]

export const messages: Record<string, Message[]> = {
  c_001: [
    {
      id: 'm_001',
      conversation_id: 'c_001',
      role: 'user',
      content: '计算 6*7',
      attachments: [],
      tool_calls: [],
      created_at: isoDate(10),
    },
    {
      id: 'm_002',
      conversation_id: 'c_001',
      role: 'assistant',
      content: '**6 × 7 = 42**\n\n| 表达式 | 结果 |\n|---|---|\n| 6 * 7 | 42 |',
      attachments: [],
      tool_calls: [
        { tool_call_id: 'tc_seed', tool_name: 'calculator', input: { expression: '6*7' }, output: { result: 42 }, status: 'done', position: 0, duration_ms: 320 },
      ],
      token_usage: { prompt_tokens: 42, completion_tokens: 30, total_tokens: 72 },
      trace_id: 'tr_seed_001',
      created_at: isoDate(9),
    },
  ],
  c_002: [
    {
      id: 'm_101',
      conversation_id: 'c_002',
      role: 'user',
      content: '什么是 SSE？',
      attachments: [],
      created_at: isoDate(30),
    },
    {
      id: 'm_102',
      conversation_id: 'c_002',
      role: 'assistant',
      content:
        'SSE（Server-Sent Events）是一种基于 HTTP 的单向服务器推送技术。\n\n```js\nconst es = new EventSource(url)\n```\n\n> 注意：EventSource 只支持 GET，需要 POST body 时需用 fetch + ReadableStream。',
      attachments: [],
      created_at: isoDate(29),
    },
  ],
}

export const tasks: Task[] = [
  {
    id: 'task_done',
    agent_id: 'ag_search',
    status: 'done',
    progress: 100,
    input: { message: '整理资料' },
    output: { summary: '已完成整理' },
    created_at: isoDate(45),
    updated_at: isoDate(40),
  },
  {
    id: 'task_running',
    agent_id: 'ag_calc',
    status: 'running',
    progress: 60,
    input: { message: '批量计算' },
    created_at: isoDate(5),
    updated_at: isoDate(2),
  },
]

export const kbCollections: KbCollection[] = [
  { id: 'kbc_001', name: '产品手册', chunk_size: 512, overlap: 32, document_count: 2, created_at: isoDate(200) },
  { id: 'kbc_002', name: '团队规范', chunk_size: 768, overlap: 48, document_count: 1, created_at: isoDate(150) },
]

export const kbDocuments: KbDocument[] = [
  { id: 'kbd_001', collection_id: 'kbc_001', name: '入门指南.md', mime_type: 'text/markdown', size: 12_400, status: 'indexed', chunk_count: 18, progress: 100, created_at: isoDate(120) },
  { id: 'kbd_002', collection_id: 'kbc_001', name: 'API 参考.md', mime_type: 'text/markdown', size: 33_800, status: 'indexed', chunk_count: 41, progress: 100, created_at: isoDate(110) },
  { id: 'kbd_003', collection_id: 'kbc_002', name: '代码规范.md', mime_type: 'text/markdown', size: 8_900, status: 'indexed', chunk_count: 12, progress: 100, created_at: isoDate(90) },
]

export const memoryTraces: MemoryTrace[] = [
  { id: 'mt_001', conversation_id: 'c_001', summary: '用户询问数学计算', created_at: isoDate(60) },
  { id: 'mt_002', conversation_id: 'c_002', summary: '用户了解流式协议', created_at: isoDate(30) },
]

export const longtermMemories: LongTermMemory[] = [
  {
    id: 'lm_001',
    card_type: 'json_card',
    title: '用户画像',
    body: { backstory: '平台管理员，负责搭建 Agent 平台。', person: { name: '管理员', role: 'admin' }, relationship: { trust: 'high' } },
    tags: ['user-profile'],
    importance: 5,
    created_at: isoDate(300),
  },
  {
    id: 'lm_002',
    card_type: 'note',
    title: '偏好：简洁回答',
    body: { content: '用户偏好简洁直接的回复风格。' },
    tags: ['preference'],
    importance: 3,
    created_at: isoDate(200),
  },
]

export const notifications: Notification[] = [
  { id: 'n_001', title: '评估集「基础对话」通过', body: '回归通过率 96.5%', level: 'success', read: false, created_at: isoDate(8) },
  { id: 'n_002', title: '任务 task_running 运行中', body: '进度 60%', level: 'info', read: false, created_at: isoDate(5) },
  { id: 'n_003', title: 'LLM 错误率恢复正常', body: 'Provider 故障已恢复', level: 'warning', read: true, created_at: isoDate(60) },
]

export const systemLogs: SystemLog[] = [
  { id: 'sl_001', trace_id: 'tr_seed_001', level: 'INFO', event: 'chat.complete', service: 'backend', message: '对话完成', duration_ms: 812, created_at: isoDate(9) },
  { id: 'sl_002', trace_id: 'tr_seed_001', level: 'INFO', event: 'tool.exec', service: 'worker', message: 'calculator ok', input: { expression: '6*7' }, output: { result: 42 }, duration_ms: 320, created_at: isoDate(9) },
  { id: 'sl_003', trace_id: 'tr_abc', level: 'ERROR', event: 'llm.call', service: 'backend', message: 'LLM 调用超时', duration_ms: 30_010, created_at: isoDate(35) },
  { id: 'sl_004', trace_id: 'tr_abc', level: 'WARNING', event: 'task.retry', service: 'worker', message: '任务重试第 2 次', created_at: isoDate(35) },
]

/** 新建 Agent 的默认工具（供 F1 编辑时选中） */
export function agentTemplate(): AgentConfigInput {
  return {
    name: '新 Agent',
    model: 'gpt-4o',
    system_prompt: '你是一个通用助手。',
    skills: [],
    tools: ['tl_time_now'],
    graph_template: 'single',
    max_steps: 50,
  }
}

