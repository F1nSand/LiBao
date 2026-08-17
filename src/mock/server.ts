import type { IncomingMessage, ServerResponse } from 'node:http'
import type { ChatRequest, KbCollection, ToolDefinition } from '@/types'
import {
  users,
  DEFAULT_AGENT_ID,
  tools,
  conversations,
  messages,
  tasks,
  kbCollections,
  kbDocuments,
  memoryTraces,
  longtermMemories,
  notifications,
  systemLogs,
} from './db'
import { ok, fail, json, signMockToken, decodeMockToken, paginate, uid, randHex, isoDate, fast } from './util'
import { buildChatScript, buildResumeScript, buildTaskEventsScript, toEnvelope } from './stream'
import { buildLongConversationNodes, buildTrajectoryNodes, paginateTrajectory } from './trajectory'

/* ---------- 工具函数 ---------- */

interface ParsedBody {
  json?: Record<string, any>
  files?: Array<{ name: string; filename: string; mimeType: string; size: number }>
}

/** mock 评估集用例（内存态，dev 重启重置；后端契约对齐 docs 03 §5.8） */
const mockEvalCases: Record<string, Array<Record<string, unknown>>> = {
  es_001: Array.from({ length: 8 }, (_, i) => ({
    id: `ec_${i + 1}`,
    eval_set_id: 'es_001',
    input: `用例 ${i + 1}：加两个数`,
    expected: i % 2 ? '返回正确结果' : '返回计算结果',
    layer: `L${(i % 5) + 1}`,
    active: true,
  })),
  es_002: Array.from({ length: 6 }, (_, i) => ({
    id: `ec2_${i + 1}`,
    eval_set_id: 'es_002',
    input: `工具用例 ${i + 1}`,
    expected: '调用工具并返回结果',
    layer: `L${(i % 5) + 1}`,
    active: true,
  })),
}

/** mock webhook / provider 配置（内存态；provider 契约见 api/provider.ts） */
const mockHooks: Array<Record<string, unknown>> = [
  { id: 'hk_001', tool_id: 'tl_demo_notify', conversation_id: 'c_001', enabled: true, created_at: isoDate(120) },
]
const mockProviders: Array<Record<string, unknown>> = [
  { id: 'pv_001', name: 'openai', base_url: 'https://api.openai.com/v1', model: 'gpt-4o', enabled: true, has_key: true, created_at: isoDate(200) },
  { id: 'pv_002', name: 'deepseek', base_url: '', model: 'deepseek-chat', enabled: false, has_key: true, created_at: isoDate(100) },
]

function readBody(req: IncomingMessage): Promise<ParsedBody> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = []
    req.on('data', (c: Buffer) => chunks.push(c))
    req.on('end', () => {
      const raw = Buffer.concat(chunks)
      const ct = req.headers['content-type'] ?? ''
      if (ct.includes('application/json')) {
        try {
          resolve({ json: JSON.parse(raw.toString('utf-8')) })
        } catch {
          resolve({})
        }
        return
      }
      if (ct.includes('multipart/form-data')) {
        const text = raw.toString('latin1')
        const fileMatch = text.match(/filename="([^"]+)"/)
        const nameMatch = text.match(/name="([^"]+)"[^\n]*\n\n([\s\S]*?)\n--/)
        resolve({
          files: [
            {
              name: nameMatch?.[1] ?? 'file',
              filename: fileMatch?.[1] ?? 'upload.bin',
              mimeType: ct.split(';')[0] ?? 'application/octet-stream',
              size: raw.byteLength,
            },
          ],
        })
        return
      }
      resolve({})
    })
  })
}

function currentUser(req: IncomingMessage): (typeof users)[number] | null {
  const h = req.headers.authorization
  if (!h?.startsWith('Bearer ')) return null
  const decoded = decodeMockToken(h.slice(7))
  if (!decoded) return null
  return users.find((u) => u.id === decoded.id) ?? null
}

function parseUrl(req: IncomingMessage): { pathname: string; query: URLSearchParams } {
  let url = req.url ?? '/'
  if (url.startsWith('/api/v1')) url = url.slice('/api/v1'.length)
  if (url === '') url = '/'
  const idx = url.indexOf('?')
  const pathname = idx >= 0 ? url.slice(0, idx) : url
  const query = new URLSearchParams(idx >= 0 ? url.slice(idx + 1) : '')
  return { pathname, query }
}

function match(pathname: string, pattern: string): Record<string, string> | null {
  const parts = pathname.split('/').filter(Boolean)
  const pats = pattern.split('/').filter(Boolean)
  if (parts.length !== pats.length) return null
  const params: Record<string, string> = {}
  for (let i = 0; i < pats.length; i++) {
    if (pats[i].startsWith(':')) params[pats[i].slice(1)] = decodeURIComponent(parts[i])
    else if (pats[i] !== parts[i]) return null
  }
  return params
}

/** SSE 写流：逐条 setTimeout，keepalive 保活，close 清理 */
function sendSse(
  req: IncomingMessage,
  res: ServerResponse,
  script: Array<{ type: string; payload: unknown; delayMs: number }>,
): void {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  })
  let seq = 1
  const timers: Array<ReturnType<typeof setTimeout>> = []
  let t = 0
  for (const item of script) {
    t += item.delayMs
    const env = toEnvelope(item as any, seq++)
    timers.push(
      setTimeout(() => {
        if (res.writableEnded) return
        res.write(`event: ${env.type}\ndata: ${JSON.stringify(env)}\n\n`)
      }, t),
    )
  }
  const keepalive = setInterval(() => {
    if (!res.writableEnded) res.write(': keepalive\n\n')
  }, 15_000)
  timers.push(keepalive as unknown as ReturnType<typeof setTimeout>)
  timers.push(
    setTimeout(() => {
      clearInterval(keepalive)
      if (!res.writableEnded) res.end()
    }, t + 100),
  )
  const cleanup = () => timers.forEach((tm) => clearTimeout(tm))
  res.on('close', cleanup)
  req.on('close', cleanup)
}

const isSseAccept = (req: IncomingMessage) => (req.headers.accept ?? '').includes('text/event-stream')

/* ---------- 主入口 ---------- */

export const mockServer = {
  async handle(req: IncomingMessage, res: ServerResponse, _next: () => void): Promise<void> {
    const { pathname, query } = parseUrl(req)
    const method = (req.method ?? 'GET').toUpperCase()
    const user = currentUser(req)
    const body = await readBody(req)

    // SSE 端点（无需鉴权前置在路由内处理）
    if (method === 'POST' && pathname === '/chat/stream') {
      if (!user) return void json(res, fail(40101, '未登录'), 401)
      const chatReq = (body.json ?? {}) as ChatRequest
      // 新会话：先注册 conversation，保证消息可持久化回读
      if (!chatReq.conversation_id) {
        const nc = {
          id: uid('c'),
          user_id: user.id,
          agent_id: DEFAULT_AGENT_ID,
          title: (chatReq.message?.content ?? '新会话').slice(0, 20),
          status: 'active',
          max_messages: 1000,
          created_at: isoDate(0),
        }
        conversations.unshift(nc)
        messages[nc.id] = []
        chatReq.conversation_id = nc.id
      }
      if (!messages[chatReq.conversation_id]) messages[chatReq.conversation_id] = []
      messages[chatReq.conversation_id].push({
        id: uid('m'),
        conversation_id: chatReq.conversation_id,
        role: 'user',
        content: chatReq.message?.content ?? '',
        attachments: [],
        tool_calls: [],
        created_at: isoDate(0),
      })
      return void sendSse(req, res, buildChatScript(chatReq))
    }

    // 统一鉴权（login 除外）
    if (pathname !== '/auth/login' && !user) {
      return void json(res, fail(40101, '未登录或 token 失效'), 401)
    }

    /* ===== 认证 ===== */
    if (method === 'POST' && pathname === '/auth/login') {
      const { username, password } = body.json ?? {}
      const u = users.find((x) => x.username === username && x.password === password)
      // 业务错误走信封（HTTP 200 + code!=0），前端按 ApiError.code 分支提示
      if (!u) return void json(res, fail(40101, '用户名或密码错误'))
      return void json(res, ok({ token: signMockToken(u), user: { id: u.id, name: u.name, role: u.role, org_id: u.org_id } }))
    }
    if (method === 'POST' && pathname === '/auth/logout') return void json(res, ok(null))
    if (method === 'GET' && pathname === '/auth/me') {
      const u = { id: user!.id, name: user!.name, role: user!.role, org_id: user!.org_id }
      return void json(res, ok(u))
    }

    /* ===== 用户 ===== */
    if (method === 'GET' && pathname === '/users') {
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 20)
      const items = users.map((u) => ({ id: u.id, username: u.username, name: u.name, role: u.role, org_id: u.org_id, enabled: u.enabled }))
      return void json(res, ok(paginate(items, page, size)))
    }
    if (method === 'POST' && pathname === '/users') {
      const b = body.json ?? {}
      const nu = { id: uid('u'), username: b.username, password: b.password ?? 'pass123', name: b.name ?? b.username, role: b.role ?? 'viewer', org_id: b.org_id, enabled: true, created_at: isoDate(0) }
      users.push(nu)
      const u = { id: nu.id, username: nu.username, name: nu.name, role: nu.role, org_id: nu.org_id, enabled: nu.enabled }
      return void json(res, ok(u))
    }
    let p = match(pathname, '/users/:id/role')
    if (method === 'PATCH' && p) {
      const u = users.find((x) => x.id === p!.id)
      if (!u) return void json(res, fail(40401, '用户不存在'))
      u.role = body.json?.role ?? u.role
      return void json(res, ok({ id: u.id, name: u.name, role: u.role }))
    }
    p = match(pathname, '/users/:id/status')
    if (method === 'PATCH' && p) {
      const u = users.find((x) => x.id === p!.id)
      if (!u) return void json(res, fail(40401, '用户不存在'))
      u.enabled = body.json?.enabled ?? u.enabled
      return void json(res, ok({ id: u.id, name: u.name, enabled: u.enabled }))
    }
    p = match(pathname, '/users/:id')
    if (method === 'DELETE' && p) return void json(res, ok(null))

    /* ===== 会话 / 消息 ===== */
    if (method === 'GET' && pathname === '/conversations') {
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 20)
      const mine = conversations.filter((c) => c.user_id === user!.id)
      return void json(res, ok(paginate(mine, page, size)))
    }
    if (method === 'POST' && pathname === '/conversations') {
      const b = body.json ?? {}
      const nc = { id: uid('c'), user_id: user!.id, agent_id: DEFAULT_AGENT_ID, title: b.title ?? '新会话', status: 'active', max_messages: 1000, created_at: isoDate(0) }
      conversations.unshift(nc)
      messages[nc.id] = []
      return void json(res, ok(nc))
    }
    p = match(pathname, '/conversations/:id')
    if (method === 'GET' && p) {
      const c = conversations.find((x) => x.id === p!.id)
      if (!c) return void json(res, fail(40401, '会话不存在'))
      return void json(res, ok(c))
    }
    if (method === 'DELETE' && p) return void json(res, ok(null))
    p = match(pathname, '/conversations/:id/messages')
    if (method === 'GET' && p) {
      const list = messages[p!.id] ?? []
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 50)
      return void json(res, ok(paginate(list, page, size)))
    }
    p = match(pathname, '/conversations/:id/trajectory')
    if (method === 'GET' && p) {
      const id = p.id
      const list = messages[id] ?? []
      const conv = conversations.find((c) => c.id === id)
      if (!conv && list.length === 0) return void json(res, fail(40401, '会话不存在'))
      // 轨迹节点：消息派生（含 c_001 演示 context/thinking/compaction）；c_long 走长会话分页
      const all = id === 'c_long' ? buildLongConversationNodes() : buildTrajectoryNodes(id, list)
      const beforeSeq = query.get('before_seq') ? Number(query.get('before_seq')) : undefined
      const limit = Number(query.get('limit') ?? 50)
      const { nodes, hasMore } = paginateTrajectory(all, beforeSeq, limit)
      return void json(res, ok({ conversation_id: id, nodes, has_more: hasMore }))
    }

    /* ===== 任务 ===== */
    if (method === 'GET' && pathname === '/tasks') {
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 20)
      let list = tasks
      const st = query.get('status')
      if (st) list = list.filter((t) => t.status === st)
      return void json(res, ok(paginate(list, page, size)))
    }
    if (method === 'POST' && pathname === '/tasks') {
      const b = body.json ?? {}
      const nt = { id: uid('task'), agent_id: DEFAULT_AGENT_ID, status: 'pending' as const, progress: 0, input: b.input, created_at: isoDate(0) }
      tasks.unshift(nt)
      return void json(res, ok({ task_id: nt.id }))
    }
    p = match(pathname, '/tasks/:id')
    if (method === 'GET' && p) {
      const t = tasks.find((x) => x.id === p!.id)
      if (!t) return void json(res, fail(40402, '任务不存在'))
      return void json(res, ok(t))
    }
    p = match(pathname, '/tasks/:id/events')
    if ((method === 'GET' || method === 'POST') && p) {
      // 契约/真实后端/TaskDetail 均为 GET（docs/03 §5.3）；POST 兼容保留
      return void sendSse(req, res, buildTaskEventsScript(p.id))
    }
    p = match(pathname, '/tasks/:id/cancel')
    if (method === 'POST' && p) {
      const t = tasks.find((x) => x.id === p!.id)
      if (t && (t.status === 'done' || t.status === 'cancelled')) return void json(res, fail(40902, '状态不可取消'))
      if (t) {
        t.status = 'cancelled'
        t.updated_at = isoDate(0)
      }
      return void json(res, ok(null))
    }
    p = match(pathname, '/tasks/:id/resume')
    if (method === 'POST' && p) {
      const approved = body.json?.confirm?.approved === true
      const t = tasks.find((x) => x.id === p!.id)
      if (isSseAccept(req)) return void sendSse(req, res, buildResumeScript(p.id, approved))
      if (t) {
        t.status = approved ? 'running' : 'cancelled'
        t.updated_at = isoDate(0)
      }
      return void json(res, ok(null))
    }

    /* ===== 工具 ===== */
    if (method === 'GET' && pathname === '/tools') {
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 20)
      return void json(res, ok(paginate(tools, page, size)))
    }
    if (method === 'POST' && pathname === '/tools') {
      const nt = { id: uid('tl'), name: body.json?.name ?? `tool_${randHex(4)}`, description: body.json?.description ?? '', params_schema: body.json?.params_schema ?? {}, tool_type: body.json?.tool_type ?? 'execution', sandbox: body.json?.sandbox ?? 'none', require_confirm: body.json?.require_confirm ?? false, idempotent: body.json?.idempotent ?? false, enabled: false, created_at: isoDate(0) } as ToolDefinition
      tools.unshift(nt)
      return void json(res, ok(nt))
    }
    if (method === 'GET' && pathname === '/tools/search') {
      const q = (query.get('q') ?? '').toLowerCase()
      const hits = tools.filter((t) => t.name.includes(q) || (t.description ?? '').toLowerCase().includes(q))
      return void json(res, ok(hits.map((t) => ({ id: t.id, name: t.name, description: t.description, enabled: t.enabled }))))
    }
    if (method === 'POST' && pathname === '/tools/mcp/register') {
      const nt = { id: uid('tl'), name: 'mcp_' + randHex(4), description: 'MCP 源接入工具', params_schema: {}, tool_type: 'execution' as const, enabled: false, require_confirm: true, sandbox: 'docker' as const, timeout_ms: 30_000, max_concurrency: 2, mcp_source: body.json?.url_or_command, created_at: isoDate(0) }
      tools.unshift(nt)
      return void json(res, ok(nt))
    }
    p = match(pathname, '/tools/:id/test')
    if (method === 'POST' && p) {
      const params = body.json?.params ?? {}
      const out = p.id === 'tl_calculator' ? { ok: true, output: { result: 42 }, duration_ms: 86 } : { ok: true, output: { echo: params }, duration_ms: 24 }
      return void json(res, ok(out))
    }
    p = match(pathname, '/tools/:id')
    if (method === 'GET' && p) {
      const t = tools.find((x) => x.id === p!.id)
      if (!t) return void json(res, fail(40401, '工具不存在'))
      return void json(res, ok(t))
    }
    if (method === 'PATCH' && p) {
      const t = tools.find((x) => x.id === p!.id)
      if (t) t.enabled = body.json?.enabled ?? t.enabled
      return void json(res, ok(t))
    }
    if (method === 'PUT' && p) {
      const t = tools.find((x) => x.id === p!.id)
      if (t) Object.assign(t, body.json)
      return void json(res, ok(t))
    }
    if (method === 'DELETE' && p) return void json(res, ok(null))

    /* ===== 知识库 ===== */
    if (method === 'GET' && pathname === '/kb/collections') return void json(res, ok(kbCollections))
    if (method === 'POST' && pathname === '/kb/collections') {
      const nc = { id: uid('kbc'), name: body.json?.name ?? '新集合', chunk_size: body.json?.chunk_size, overlap: body.json?.overlap, document_count: 0, created_at: isoDate(0) } as KbCollection
      kbCollections.unshift(nc)
      return void json(res, ok(nc))
    }
    p = match(pathname, '/kb/collections/:id')
    if (method === 'DELETE' && p) return void json(res, ok(null))
    p = match(pathname, '/kb/collections/:id/documents')
    if (method === 'GET' && p) {
      return void json(res, ok(kbDocuments.filter((d) => d.collection_id === p!.id)))
    }
    if (method === 'POST' && p) {
      const file = body.files?.[0]
      const nd = { id: uid('kbd'), collection_id: p.id, name: file?.filename ?? '文档.md', mime_type: file?.mimeType ?? 'text/markdown', size: file?.size ?? 0, status: 'chunking' as const, chunk_count: 0, progress: 10, created_at: isoDate(0) }
      kbDocuments.unshift(nd)
      return void json(res, ok(nd))
    }
    p = match(pathname, '/kb/documents/:id/status')
    if (method === 'GET' && p) {
      const d = kbDocuments.find((x) => x.id === p!.id)
      return void json(res, ok(d ? { status: d.status, chunk_count: d.chunk_count, progress: d.progress } : fail(40401, '文档不存在')))
    }
    p = match(pathname, '/kb/documents/:id/reindex')
    if (method === 'POST' && p) {
      const d = kbDocuments.find((x) => x.id === p!.id)
      if (d) {
        d.status = 'indexing'
        d.progress = 40
      }
      return void json(res, ok(d))
    }
    p = match(pathname, '/kb/documents/:id/status')
    if (method === 'PATCH' && p) {
      const d = kbDocuments.find((x) => x.id === p!.id)
      if (d) d.status = body.json?.status ?? d.status
      return void json(res, ok(d))
    }
    p = match(pathname, '/kb/documents/:id')
    if (method === 'GET' && p) {
      const d = kbDocuments.find((x) => x.id === p!.id)
      return void json(res, ok(d))
    }
    if (method === 'DELETE' && p) return void json(res, ok(null))
    if (method === 'POST' && pathname === '/kb/search') {
      const b = body.json ?? {}
      const q = b.query ?? ''
      return void json(
        res,
        ok(
          Array.from({ length: 3 }, (_, i) => ({
            chunk_id: uid('chunk'),
            text: `${q} 相关片段 ${i + 1}：这是混合检索返回的语义相关文本片段。`,
            score: +(0.9 - i * 0.1).toFixed(2),
            rerank_score: +(0.95 - i * 0.12).toFixed(2),
          })),
        ),
      )
    }

    /* ===== 记忆 ===== */
    if (method === 'GET' && pathname === '/memory/traces') {
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 20)
      return void json(res, ok(paginate(memoryTraces, page, size)))
    }
    if (method === 'GET' && pathname === '/memory/longterm') return void json(res, ok(longtermMemories))
    if (method === 'POST' && pathname === '/memory/longterm') {
      const b = body.json ?? {}
      const nm = { id: uid('lm'), card_type: b.card_type ?? 'note', title: b.title ?? '记忆', body: b.body ?? {}, tags: b.tags ?? [], importance: 3, created_at: isoDate(0) }
      longtermMemories.unshift(nm)
      return void json(res, ok(nm))
    }
    p = match(pathname, '/memory/longterm/:id/versions')
    if (method === 'GET' && p) {
      return void json(res, ok([{ id: uid('lmv'), memory_id: p.id, version: 1, title: 'v1', body: {}, created_at: isoDate(100) }]))
    }
    p = match(pathname, '/memory/longterm/:id')
    if (method === 'DELETE' && p) return void json(res, ok(null))
    if (method === 'POST' && pathname === '/memory/maintenance') {
      return void json(res, ok({ summary: '整理完成：新生成 2 张记忆卡片，3 张卡片已合并。', cards_created: 2, cards_updated: 3 }))
    }

    /* ===== 系统 / 日志 / 评估 / 成本 ===== */
    if (method === 'GET' && pathname === '/system/logs') {
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 20)
      let list = systemLogs
      const tid = query.get('trace_id')
      const lvl = query.get('level')
      if (tid) list = list.filter((l) => l.trace_id.includes(tid))
      if (lvl) list = list.filter((l) => l.level === lvl)
      return void json(res, ok(paginate(list, page, size)))
    }
    p = match(pathname, '/system/logs/trace/:trace_id')
    if (method === 'GET' && p) {
      return void json(
        res,
        ok({
          trace_id: p.trace_id,
          events: [
            { node_type: 'router', name: '主图', status: 'success', duration_ms: 12, ts: Date.now() - 3000 },
            { node_type: 'llm', name: 'LLM 调用', status: 'success', token_usage: { total_tokens: 220 }, duration_ms: 610, ts: Date.now() - 2500 },
            { node_type: 'tool', name: p.trace_id.includes('tr_seed') ? 'calculator' : 'web_search', status: 'success', duration_ms: 320, ts: Date.now() - 1500 },
          ],
        }),
      )
    }
    /* ===== 评估管理（docs 03 §5.8 / docs 06 §2.4） ===== */
    if (method === 'GET' && pathname === '/system/evals/sets') {
      return void json(res, ok([
        { id: 'es_001', name: '基础对话', description: 'M1 回归集', case_count: mockEvalCases.es_001.length, created_at: isoDate(300) },
        { id: 'es_002', name: '工具调用', description: 'M2 回归集', case_count: mockEvalCases.es_002.length, created_at: isoDate(150) },
      ]))
    }
    if (method === 'POST' && pathname === '/system/evals/sets') {
      const nc = { id: uid('es'), ...(body.json ?? {}), case_count: 0, created_at: isoDate(0) }
      return void json(res, ok(nc))
    }
    p = match(pathname, '/system/evals/sets/:id/cases/:case_id')
    if (method === 'PATCH' && p) {
      const setId = p.id
      const caseId = p.case_id
      const c = (mockEvalCases[setId] ?? []).find((x) => x.id === caseId)
      if (c && body.json?.active !== undefined) c.active = body.json.active
      return void json(res, ok(c ?? { id: caseId, active: body.json?.active ?? true }))
    }
    if (method === 'DELETE' && p) {
      const setId = p.id
      const caseId = p.case_id
      mockEvalCases[setId] = (mockEvalCases[setId] ?? []).filter((x) => x.id !== caseId)
      return void json(res, ok(null))
    }
    p = match(pathname, '/system/evals/sets/:id/cases')
    if (method === 'GET' && p) return void json(res, ok(mockEvalCases[p.id] ?? []))
    if (method === 'POST' && p) {
      const nc = { id: uid('ec'), eval_set_id: p.id, ...(body.json ?? {}), active: true, layer: body.json?.layer ?? 'L1' }
      mockEvalCases[p.id] = [...(mockEvalCases[p.id] ?? []), nc]
      return void json(res, ok(nc))
    }
    p = match(pathname, '/system/evals/sets/:id')
    if (method === 'PUT' && p) {
      const s = { id: p.id, ...(body.json ?? {}), created_at: isoDate(0) }
      return void json(res, ok(s))
    }
    if (method === 'DELETE' && p) {
      delete mockEvalCases[p.id]
      return void json(res, ok(null))
    }
    if (method === 'POST' && pathname === '/system/evals/run') {
      const rid = uid('run')
      return void json(res, ok({ id: rid, eval_set_id: body.json?.eval_set_id, baseline_run_id: body.json?.baseline_run_id ?? null, status: 'running', progress: 10, created_at: isoDate(0) }))
    }
    if (method === 'GET' && pathname === '/system/evals/runs') {
      return void json(res, ok([
        { id: 'run_001', eval_set_id: 'es_001', baseline_run_id: null, status: 'done', progress: 100, pass_rate: 0.965, created_at: isoDate(60) },
        { id: 'run_002', eval_set_id: 'es_001', baseline_run_id: 'run_001', status: 'done', progress: 100, pass_rate: 0.98, created_at: isoDate(30) },
      ]))
    }
    p = match(pathname, '/system/evals/runs/:run_id/pairwise')
    if (method === 'GET' && p) {
      const baseline = query.get('baseline_run_id') ?? 'run_001'
      const matrix = Array.from({ length: 8 }, (_, i) => ({
        case_id: `ec_${i + 1}`,
        input: `用例 ${i + 1}`,
        baseline_pass: i % 3 !== 0,
        candidate_pass: i % 3 !== 2,
        outcome: (i % 3 === 2 ? 'win' : i % 3 === 1 ? 'tie' : 'lose') as 'win' | 'lose' | 'tie',
      }))
      return void json(
        res,
        ok({
          run_id: p.run_id,
          baseline_run_id: baseline,
          matrix,
          summary: { baseline_pass_rate: 0.875, candidate_pass_rate: 0.625, delta: -0.25, wins: 3, losses: 2, ties: 3 },
        }),
      )
    }
    p = match(pathname, '/system/evals/runs/:run_id')
    if (method === 'GET' && p) {
      return void json(
        res,
        ok({
          run: { id: p.run_id, eval_set_id: 'es_001', baseline_run_id: 'run_001', status: 'done', progress: 100, pass_rate: 0.965, created_at: isoDate(0) },
          results: Array.from({ length: 5 }, (_, i) => ({
            case_id: uid('ec'),
            input: `测试用例 ${i + 1}`,
            expected: '期望输出',
            actual: i % 2 ? '输出正确' : '输出略有偏差',
            pass: i % 2 === 0,
            score: i % 2 ? 1 : 0.8,
            latency_ms: 420 + i * 30,
            cost: 0.0008 + i * 0.0001,
          })),
        }),
      )
    }
    /* ===== Webhook（docs 03 §5.10） ===== */
    if (method === 'GET' && pathname === '/hooks') return void json(res, ok(mockHooks))
    p = match(pathname, '/hooks/:tool_id/register')
    if (method === 'POST' && p) {
      const hk = { id: uid('hk'), tool_id: p.tool_id, conversation_id: body.json?.conversation_id ?? null, enabled: true, created_at: isoDate(0) }
      mockHooks.push(hk)
      return void json(res, ok(hk))
    }
    p = match(pathname, '/hooks/:tool_id')
    if (method === 'DELETE' && p) {
      const toolId = p.tool_id
      mockHooks.splice(mockHooks.findIndex((h) => h.tool_id === toolId), 1)
      return void json(res, ok(null))
    }

    /* ===== Provider 配置（前端契约，mock 演示；真实后端待实现） ===== */
    if (method === 'GET' && pathname === '/settings/providers') return void json(res, ok(mockProviders))
    if (method === 'POST' && pathname === '/settings/providers') {
      const pv = { id: uid('pv'), ...(body.json ?? {}), has_key: !!body.json?.api_key, enabled: body.json?.enabled ?? true, created_at: isoDate(0) }
      mockProviders.push(pv)
      return void json(res, ok(pv))
    }
    p = match(pathname, '/settings/providers/:id')
    if (method === 'PATCH' && p) {
      const id = p.id
      const pv = mockProviders.find((x) => x.id === id)
      if (pv) Object.assign(pv, body.json)
      return void json(res, ok(pv))
    }
    if (method === 'DELETE' && p) {
      const id = p.id
      mockProviders.splice(mockProviders.findIndex((x) => x.id === id), 1)
      return void json(res, ok(null))
    }

    if (method === 'GET' && pathname === '/system/cost') {
      return void json(
        res,
        ok({
          total_cost: 12.47,
          total_calls: 1840,
          by_provider: [
            { provider: 'openai', cost: 8.2, calls: 1100 },
            { provider: 'deepseek', cost: 4.27, calls: 740 },
          ],
          series: Array.from({ length: 14 }, (_, i) => ({
            date: new Date(Date.now() - (13 - i) * 86_400_000).toISOString().slice(0, 10),
            cost: +(0.4 + Math.random() * 1.2).toFixed(2),
            calls: Math.round(60 + Math.random() * 120),
          })),
        }),
      )
    }

    /* ===== 附件 ===== */
    if (method === 'POST' && pathname === '/uploads') {
      const f = body.files?.[0]
      return void json(res, ok({ attachment_id: uid('atc'), mime_type: f?.mimeType ?? 'text/plain', size: f?.size ?? 1024, status: 'uploaded' }))
    }
    p = match(pathname, '/attachments/:id/analysis')
    if (method === 'GET' && p) {
      const analyzing = !fast()
      return void json(
        res,
        ok(analyzing ? { attachment_id: p.id, status: 'analyzing' } : { attachment_id: p.id, status: 'ready', summary: '这是一张示例图片，已识别出主要元素与文字。', extracted_text: '示例文字识别结果。' }),
      )
    }
    p = match(pathname, '/attachments/:id')
    if (method === 'GET' && p) return void json(res, ok({ id: p.id, mime_type: 'image/png', size: 2048, status: 'ready', created_at: isoDate(1) }))
    if (method === 'DELETE' && p) return void json(res, ok(null))

    /* ===== 通知 ===== */
    if (method === 'GET' && pathname === '/notifications') {
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 20)
      return void json(res, ok(paginate(notifications, page, size)))
    }
    if (method === 'GET' && pathname === '/notifications/stream') {
      const timer = setTimeout(() => {
        const n = { id: uid('n'), title: '新系统事件', body: '有新的评估结果已生成', level: 'info', read: false, created_at: isoDate(0) }
        const env = { id: `evt_n_${randHex(4)}`, seq: 1, type: 'notification', ts: Date.now(), payload: n }
        if (!res.writableEnded) res.write(`event: notification\ndata: ${JSON.stringify(env)}\n\n`)
      }, 3000)
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' })
      res.write(': keepalive\n\n')
      const keep = setInterval(() => {
        if (!res.writableEnded) res.write(': keepalive\n\n')
      }, 15_000)
      req.on('close', () => {
        clearTimeout(timer)
        clearInterval(keep)
      })
      return
    }
    p = match(pathname, '/notifications/:id/read')
    if (method === 'PATCH' && p) {
      const n = notifications.find((x) => x.id === p!.id)
      if (n) n.read = true
      return void json(res, ok(n))
    }

    // 未命中
    return void json(res, fail(40401, `mock 未实现：${method} ${pathname}`), 404)
  },
}
