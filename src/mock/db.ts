import type {
  Candidate,
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
  // org_2（多租户数据隔离演示：组织筛选可切到第二组织）
  { id: 'u_dev2', username: 'dev2', password: 'dev2123', name: '开发者二组', role: 'developer', org_id: 'org_2', enabled: true, created_at: isoDate(40) },
  { id: 'u_view2', username: 'viewer2', password: 'viewer2123', name: '访客二组', role: 'viewer', org_id: 'org_2', enabled: true, created_at: isoDate(35) },
]

// 单通用 Agent 模型：chat/conversation/task 固定用组织默认通用 Agent（无 /agents 端点）
export const DEFAULT_AGENT_ID = 'ag_default'

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
  { id: 'c_001', user_id: 'u_admin', agent_id: DEFAULT_AGENT_ID, title: '计算 6*7', status: 'active', max_messages: 1000, last_message_at: isoDate(10), created_at: isoDate(60) },
  { id: 'c_002', user_id: 'u_admin', agent_id: DEFAULT_AGENT_ID, title: '什么是 SSE', status: 'active', max_messages: 1000, last_message_at: isoDate(30), created_at: isoDate(90) },
  { id: 'c_long', user_id: 'u_admin', agent_id: DEFAULT_AGENT_ID, title: '长会话（轨迹分页演示）', status: 'active', max_messages: 1000, last_message_at: isoDate(20), created_at: isoDate(180) },
  { id: 'c_scroll', user_id: 'u_admin', agent_id: DEFAULT_AGENT_ID, title: '滚动测试长会话', status: 'active', max_messages: 1000, last_message_at: isoDate(4), created_at: isoDate(200) },
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
  // 长会话（滚动位置记忆/恢复 e2e）：12 条交替消息，足够高可滚动
  c_scroll: Array.from({ length: 12 }, (_, i) => {
    const isUser = i % 2 === 0
    const base = Math.floor(i / 2) + 1
    return {
      id: `ms_${i + 1}`,
      conversation_id: 'c_scroll',
      role: isUser ? 'user' : 'assistant',
      content: isUser
        ? `第 ${base} 个问题：请说明主题 ${base}。`
        : `主题 ${base} 的说明：\n\n这是回答的第 ${base} 部分，包含若干行文本，用来让会话内容足够高以支持滚动测试。\n\n- 要点一\n- 要点二\n- 要点三\n\n以上是对问题 ${base} 的回答。`,
      attachments: [],
      tool_calls: [],
      created_at: isoDate(24 - i * 2),
    }
  }),
}

export const tasks: Task[] = [
  {
    id: 'task_done',
    agent_id: DEFAULT_AGENT_ID,
    status: 'done',
    progress: 100,
    input: { message: '整理资料' },
    output: { summary: '已完成整理' },
    created_at: isoDate(45),
    updated_at: isoDate(40),
  },
  {
    id: 'task_running',
    agent_id: DEFAULT_AGENT_ID,
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

/** 经验候选区种子（M6 契约提案 docs/06 §5：候选 → 验证 → 批准 → 发布 → 回滚） */
export const candidates: Candidate[] = [
  {
    id: 'cand_1',
    title: 'calculator 对无表达式入参应返回错误而非默认 42',
    source_conversation_id: 'c_001',
    source_type: 'trajectory',
    change_type: 'prompt',
    status: 'candidate',
    evidence: '用户发「计算」无表达式时返回 42，非报错。',
    root_cause: '提示词未要求校验入参存在性。',
    proposed_change: 'calculator 调用前校验 expression 字段非空，缺失返回明确错误。',
    expected_fix: '无表达式 → 返回「缺少表达式」。',
    affected_behaviors: ['calculator 入参校验'],
    validation_cases: ['输入「计算」应返回缺参错误；输入「计算 6*7」仍返回 42'],
    created_at: isoDate(120),
    updated_at: isoDate(100),
  },
  {
    id: 'cand_2',
    title: 'web_search 结果超 5 条时应提示数量',
    source_type: 'eval',
    change_type: 'skill',
    status: 'candidate',
    evidence: '评估用例「搜索 python」返回条数不明确。',
    root_cause: '技能未规定摘要计数。',
    proposed_change: '回复开头注明「找到 N 条相关结果」。',
    expected_fix: '搜索回复带结果计数。',
    affected_behaviors: ['web_search 回复格式'],
    validation_cases: ['「搜索 python」回复含「找到 N 条」'],
    created_at: isoDate(90),
  },
  {
    id: 'cand_3',
    title: '长上下文任务应主动压缩历史（验证中）',
    source_type: 'trajectory',
    change_type: 'context',
    status: 'validating',
    evidence: 'c_long 会话 token 逼近上限。',
    root_cause: '上下文管理未启用压缩。',
    proposed_change: '上下文超阈值时触发 compaction。',
    expected_fix: '长会话继续可用不丢关键事实。',
    affected_behaviors: ['上下文窗口管理'],
    validation_cases: ['c_long 会话持续对话 20 轮'],
    created_at: isoDate(60),
    updated_at: isoDate(30),
  },
  {
    id: 'cand_4',
    title: '天气工具描述补充单位（已批准待发布）',
    source_type: 'manual',
    change_type: 'tool',
    status: 'approved',
    evidence: '用户误读温度单位。',
    root_cause: '工具描述未注明摄氏度。',
    proposed_change: 'weather 描述加「默认摄氏度」。',
    expected_fix: '回复明确单位。',
    affected_behaviors: ['weather 工具描述'],
    validation_cases: ['「北京天气」回复含 ℃'],
    created_at: isoDate(40),
    updated_at: isoDate(10),
  },
  {
    id: 'cand_5',
    title: 'subagent 派发说明补默认职责（已发布）',
    source_type: 'trajectory',
    change_type: 'skill',
    status: 'published',
    evidence: 'research 派发偶发无任务描述。',
    root_cause: '派发 prompt 未给默认任务模板。',
    proposed_change: 'dispatch_subagent 缺 task 时用默认调研模板。',
    expected_fix: '派发始终携带可执行任务。',
    affected_behaviors: ['subagent 派发'],
    validation_cases: ['「帮我调研 X」始终触发 research'],
    created_at: isoDate(200),
    updated_at: isoDate(20),
  },
]

export const systemLogs: SystemLog[] = [
  { id: 'sl_001', trace_id: 'tr_seed_001', level: 'INFO', event: 'chat.complete', service: 'backend', message: '对话完成', duration_ms: 812, created_at: isoDate(9) },
  { id: 'sl_002', trace_id: 'tr_seed_001', level: 'INFO', event: 'tool.exec', service: 'worker', message: 'calculator ok', input: { expression: '6*7' }, output: { result: 42 }, duration_ms: 320, created_at: isoDate(9) },
  { id: 'sl_003', trace_id: 'tr_abc', level: 'ERROR', event: 'llm.call', service: 'backend', message: 'LLM 调用超时', duration_ms: 30_010, created_at: isoDate(35) },
  { id: 'sl_004', trace_id: 'tr_abc', level: 'WARNING', event: 'task.retry', service: 'worker', message: '任务重试第 2 次', created_at: isoDate(35) },
]

