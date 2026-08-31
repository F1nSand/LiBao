import type {
  Conversation,
  KbCollection,
  KbDocument,
  LongTermMemory,
  Message,
  Notification,
  Skill,
  SystemLog,
  Task,
  ToolDefinition,
  Workspace,
  WorkspaceFile,
} from '@/types'
import { isoDate } from './util'

/** Mock 种子数据（内存态，dev 重启即重置） */

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
    meta: false,
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
    meta: false,
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
    meta: false,
    require_confirm: false,
    sandbox: 'docker',
    timeout_ms: 30_000,
    max_concurrency: 3,
    mcp_source: null,
    idempotent: true,
    created_at: isoDate(180),
  },
  {
    id: 'tl_tool_search',
    name: 'tool_search',
    description: '工具发现元工具：搜索工具目录定位可用工具（模型侧常驻，无需再经工具发现）。',
    params_schema: { type: 'object', properties: { query: { type: 'string', description: '搜索关键词' } }, required: ['query'] },
    tool_type: 'perception',
    enabled: true,
    meta: true,
    require_confirm: false,
    sandbox: 'none',
    timeout_ms: 5000,
    max_concurrency: 10,
    mcp_source: null,
    idempotent: true,
    created_at: isoDate(170),
  },
]

export const conversations: Conversation[] = [
  { id: 'c_001', user_id: 'u_admin', agent_id: DEFAULT_AGENT_ID, title: '计算 6*7', status: 'active', max_messages: 1000, last_message_at: isoDate(10), created_at: isoDate(60) },
  { id: 'c_002', user_id: 'u_admin', agent_id: DEFAULT_AGENT_ID, title: '什么是 SSE', status: 'active', max_messages: 1000, last_message_at: isoDate(30), created_at: isoDate(90) },
  { id: 'c_long', user_id: 'u_admin', agent_id: DEFAULT_AGENT_ID, title: '长会话（轨迹分页演示）', status: 'active', max_messages: 1000, last_message_at: isoDate(20), created_at: isoDate(180) },
  { id: 'c_scroll', user_id: 'u_admin', agent_id: DEFAULT_AGENT_ID, title: '滚动测试长会话', status: 'active', max_messages: 1000, last_message_at: isoDate(4), created_at: isoDate(200) },
  // 工作区会话（M7-B）：GET /conversations 无 workspace_id 时排除，只在工作区页可见
  { id: 'c_ws1', user_id: 'u_admin', agent_id: DEFAULT_AGENT_ID, title: '工作区：产品文档', status: 'active', max_messages: 1000, workspace_id: 'ws_001', last_message_at: isoDate(6), created_at: isoDate(30) },
  { id: 'c_ws2', user_id: 'u_admin', agent_id: DEFAULT_AGENT_ID, title: '工作区：数据管线', status: 'active', max_messages: 1000, workspace_id: 'ws_002', last_message_at: isoDate(3), created_at: isoDate(20) },
]

export const messages: Record<string, Message[]> = {
  c_001: [
    {
      id: 'm_001',
      conversation_id: 'c_001',
      role: 'user',
      content: '计算 6*7',
      checkpoint_id: 'cp_001',
      checkpoint: {
        id: 'cp_001', status: 'sealed', changed_file_count: 0,
        can_restore_code: true, can_restore_conversation: true,
      },
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
  // 工作区会话消息（M7-B）
  c_ws1: [
    {
      id: 'mws_1',
      conversation_id: 'c_ws1',
      role: 'user',
      content: '总结一下 README 的要点',
      attachments: [],
      tool_calls: [],
      created_at: isoDate(6),
    },
    {
      id: 'mws_2',
      conversation_id: 'c_ws1',
      role: 'assistant',
      content: 'README 包含「快速开始」与「常见问题」两个模块。',
      attachments: [],
      tool_calls: [],
      created_at: isoDate(5),
    },
  ],
  c_ws2: [
    {
      id: 'mws2_1',
      conversation_id: 'c_ws2',
      role: 'user',
      content: 'pipeline.py 做什么？',
      attachments: [],
      tool_calls: [],
      created_at: isoDate(3),
    },
  ],
}

export const checkpointHistory: Record<string, { kind: 'checkpoint' | 'rollback_operation'; id: string; user_message_id?: string; target_checkpoint_id?: string; status: string; mode?: string; changed_file_count?: number; created_at: string }[]> = {
  c_001: [{ kind: 'checkpoint', id: 'cp_001', user_message_id: 'm_001', status: 'sealed', changed_file_count: 0, created_at: isoDate(10) }],
}

/** Skills 种子（M7-A 简化 2026-08-25：两级目录——全局 + 工作区，删 org CRUD） */
export const skills: Skill[] = [
  {
    name: 'python-代码审查',
    description: '审查 Python 代码：发现 bug、安全隐患与可读性问题。用户请求代码评审时使用。',
    path: 'skills/python-代码审查/SKILL.md',
  },
  {
    name: 'sql-查询优化',
    description: 'SQL 查询优化：改写慢查询、补充索引建议。用户请求优化查询/排查慢 SQL 时使用。',
    path: 'skills/sql-查询优化/SKILL.md',
  },
]

/** Workspaces 种子（M7-B 契约，交接板 2026-08-20；org 级、active） */
export const workspaces: Workspace[] = [
  { id: 'ws_001', org_id: 'org_1', name: '产品文档', description: '产品文档与入门指南写作工作区', root_path: 'C:\\Users\\Admin1\\Desktop\\demo\\product-docs', status: 'active', created_by: 'u_admin', created_at: isoDate(90) },
  { id: 'ws_002', org_id: 'org_1', name: '数据管线', description: '数据采集与清洗管线开发', root_path: 'C:\\Users\\Admin1\\Desktop\\demo\\data-pipeline', status: 'active', created_by: 'u_admin', created_at: isoDate(60) },
]

/** 工作区文件树（扁平 list，path 相对 root 含层级；列目录按父路径过滤） */
export const workspaceFiles: Record<string, WorkspaceFile[]> = {
  ws_001: [
    { name: 'README.md', path: 'README.md', is_dir: false, size: 320 },
    { name: 'docs', path: 'docs', is_dir: true, size: 0 },
    { name: 'docs/入门指南.md', path: 'docs/入门指南.md', is_dir: false, size: 1280 },
    { name: 'docs/API 参考.md', path: 'docs/API 参考.md', is_dir: false, size: 2400 },
    { name: 'src', path: 'src', is_dir: true, size: 0 },
    { name: 'src/main.py', path: 'src/main.py', is_dir: false, size: 640 },
    // .agent/ 项目级能力目录（M7-B 收敛，《02》前端设计 §4.2）：skills/记忆/知识库文件化，agent 自动发现叠加
    { name: '.agent', path: '.agent', is_dir: true, size: 0 },
    { name: '.agent/README.md', path: '.agent/README.md', is_dir: false, size: 220 },
    { name: '.agent/agent.md', path: '.agent/agent.md', is_dir: false, size: 320 },
    { name: '.agent/skills', path: '.agent/skills', is_dir: true, size: 0 },
    { name: '.agent/skills/project-lint', path: '.agent/skills/project-lint', is_dir: true, size: 0 },
    { name: '.agent/skills/project-lint/SKILL.md', path: '.agent/skills/project-lint/SKILL.md', is_dir: false, size: 780 },
    { name: '.agent/memory', path: '.agent/memory', is_dir: true, size: 0 },
    { name: '.agent/memory/项目约定.md', path: '.agent/memory/项目约定.md', is_dir: false, size: 360 },
    { name: '.agent/knowledge', path: '.agent/knowledge', is_dir: true, size: 0 },
    { name: '.agent/knowledge/架构说明.md', path: '.agent/knowledge/架构说明.md', is_dir: false, size: 540 },
  ],
  ws_002: [
    { name: 'pipeline.py', path: 'pipeline.py', is_dir: false, size: 1500 },
    { name: 'data', path: 'data', is_dir: true, size: 0 },
    { name: 'data/input.json', path: 'data/input.json', is_dir: false, size: 800 },
  ],
}

/** 文件正文（key = `workspaceId|path`；读超 50K 截断） */
export const workspaceFileContents: Record<string, string> = {
  'ws_001|README.md': '# 产品文档工作区\n\n这是示例 README，供工作区文件引用测试。\n\n- 快速开始\n- 常见问题\n',
  'ws_001|docs/入门指南.md': '# 入门指南\n\n1. 安装依赖\n2. 初始化配置\n3. 启动服务\n',
  'ws_001|docs/API 参考.md': '# API 参考\n\n`GET /api/v1/workspaces` 列出工作区。\n',
  'ws_001|src/main.py': 'def main():\n    print("hello workspace")\n\nif __name__ == "__main__":\n    main()\n',
  'ws_001|.agent/README.md': '# .agent — 项目级能力目录\n\n本项目级能力（skills / 记忆 / 知识库）随工作区自动发现，agent 工作时优先读取并叠加到全局能力。\n\n- `skills/` 项目级技能\n- `memory/` 项目级长期记忆\n- `knowledge/` 项目级知识库\n- `agent.md` 项目约定（经消息通道注入，非 system_prompt）\n',
  'ws_001|.agent/agent.md': '# 项目约定\n\n- 文档写作遵循「面向用户」原则\n- 代码风格：PEP8 + 类型注解\n',
  'ws_001|.agent/skills/project-lint/SKILL.md': '---\nname: project-lint\ndescription: 项目代码风格检查（PEP8 + 类型注解）\n---\n\n对工作区代码执行风格检查，输出不合规项与修改建议。\n',
  'ws_001|.agent/memory/项目约定.md': '# 项目约定\n\n团队采用中文文档、英文代码注释；架构评审须附时序图。\n',
  'ws_001|.agent/knowledge/架构说明.md': '# 架构说明\n\n本工作区为产品文档与入门指南写作，核心模块：docs/ 源稿、src/ 构建脚本。\n',
  'ws_002|pipeline.py': 'def run():\n    # 数据清洗管线\n    pass\n',
  'ws_002|data/input.json': '{\n  "source": "mock",\n  "rows": 128\n}\n',
}

/** 上传附件注册表（mock 仅用于验证上传元数据、预览和聊天语义；重启即清空） */
export interface MockAttachmentRecord {
  attachment_id: string
  name: string
  mime_type: string
  size: number
  bytes: Buffer
}

export const uploadedAttachments = new Map<string, MockAttachmentRecord>()

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
  {
    id: 'task_failed_recoverable',
    agent_id: DEFAULT_AGENT_ID,
    status: 'failed',
    progress: 40,
    input: { message: '断点恢复演示' },
    error: { code: 60005, message: '模型连接中断', kind: 'llm_transport', retryable: true, recoverable: true, details: {} },
    recovery_attempts: 0,
    created_at: isoDate(3),
    updated_at: isoDate(1),
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
