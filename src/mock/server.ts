import type { IncomingMessage, ServerResponse } from 'node:http'
import type { ChatRequest, KbCollection, KbDocument, Skill, ToolDefinition, Workspace } from '@/types'
import {
  users,
  candidates,
  DEFAULT_AGENT_ID,
  tools,
  skills,
  workspaces,
  workspaceFiles,
  workspaceFileContents,
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
import { buildChatScript, buildResumeScript, toEnvelope } from './stream'
import { buildLongConversationNodes, buildTrajectoryNodes, paginateTrajectory } from './trajectory'

/* ---------- 工具函数 ---------- */

interface ParsedBody {
  json?: Record<string, any>
  files?: Array<{ name: string; filename: string; mimeType: string; size: number }>
}

/** mock webhook / provider 配置（内存态；provider 契约见 api/provider.ts） */
const mockHooks: Array<Record<string, unknown>> = [
  { id: 'hk_001', tool_id: 'tl_demo_notify', conversation_id: 'c_001', enabled: true, created_at: isoDate(120) },
]
const mockProviders: Array<Record<string, unknown>> = [
  { id: 'pv_001', name: 'openai', base_url: 'https://api.openai.com/v1', model: 'gpt-4o', enabled: true, has_key: true, created_at: isoDate(200) },
  { id: 'pv_002', name: 'deepseek', base_url: '', model: 'deepseek-chat', enabled: false, has_key: true, created_at: isoDate(100) },
]

/** M7-B 演示「外部写文件」：首次拉取 ws_001 文件列表后延迟注入一个新文件（文件树轮询应自动捕获） */
let ws001Injected = false

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
        // latin1 逐字节读保位置，再还原 UTF-8：浏览器按 UTF-8 发非 ASCII 文件名（如中文），latin1 直读会乱码
        const text = raw.toString('latin1')
        const fileMatch = text.match(/filename="([^"]*)"/)
        const nameMatch = text.match(/name="([^"]+)"[^\n]*\n\n([\s\S]*?)\n--/)
        const decodeName = (s: string | undefined): string => (s ? Buffer.from(s, 'latin1').toString('utf-8') : '')
        resolve({
          files: [
            {
              name: decodeName(nameMatch?.[1]) || 'file',
              filename: decodeName(fileMatch?.[1]) || 'upload.bin',
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

/**
 * mock KB 处理链（对齐真实后端 kb_pipeline）：uploaded→chunking→indexing→indexed。
 * 正常模式 ~1s/步（demo 可见推进）；e2e fast 模式 ~150ms/步（首轮轮询前收敛到可断言终态）。
 */
function simulateKbChain(doc: KbDocument): void {
  const step = fast() ? 150 : 1000
  setTimeout(() => {
    if (doc.status === 'uploaded') {
      doc.status = 'chunking'
      doc.progress = 40
    }
  }, step)
  setTimeout(() => {
    if (doc.status === 'chunking') {
      doc.status = 'indexing'
      doc.progress = 70
    }
  }, step * 2)
  setTimeout(() => {
    if (doc.status === 'indexing') {
      doc.status = 'indexed'
      doc.progress = 100
      doc.chunk_count = Math.max(1, Math.ceil((doc.size || 1024) / 512))
    }
  }, step * 3)
}

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
      // 新会话：先注册 conversation，保证消息可持久化回读（工作区对话带 workspace_id）
      if (!chatReq.conversation_id) {
        const nc = {
          id: uid('c'),
          user_id: user.id,
          agent_id: DEFAULT_AGENT_ID,
          title: (chatReq.message?.content ?? '新会话').slice(0, 20),
          status: 'active',
          max_messages: 1000,
          workspace_id: chatReq.workspace_id ?? undefined,
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
        file_refs: chatReq.message?.file_refs ?? [],
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
      return void json(res, ok({ token: signMockToken(u), user: { id: u.id, name: u.name, role: u.role, org_id: u.org_id, org_name: u.org_name } }))
    }
    if (method === 'POST' && pathname === '/auth/logout') return void json(res, ok(null))
    if (method === 'GET' && pathname === '/auth/me') {
      const u = { id: user!.id, name: user!.name, role: user!.role, org_id: user!.org_id, org_name: user!.org_name }
      return void json(res, ok(u))
    }

    /* ===== 用户 ===== */
    if (method === 'GET' && pathname === '/users') {
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 20)
      const items = users.map((u) => ({ id: u.id, username: u.username, name: u.name, role: u.role, org_id: u.org_id, org_name: u.org_name, enabled: u.enabled }))
      return void json(res, ok(paginate(items, page, size)))
    }
    if (method === 'POST' && pathname === '/users') {
      const b = body.json ?? {}
      const nu = { id: uid('u'), username: b.username, password: b.password ?? 'pass123', name: b.name ?? b.username, role: b.role ?? 'viewer', org_id: b.org_id, org_name: b.org_name, enabled: true, created_at: isoDate(0) }
      users.push(nu)
      const u = { id: nu.id, username: nu.username, name: nu.name, role: nu.role, org_id: nu.org_id, org_name: nu.org_name, enabled: nu.enabled }
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

    /* ===== 经验候选区（M6 契约提案 docs/06 §5：候选 → 验证 → 批准 → 发布 → 回滚） ===== */
    if (method === 'GET' && pathname === '/evolution/candidates') {
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 20)
      const status = query.get('status')
      const search = query.get('search')?.trim()
      let list = candidates
      if (status) list = list.filter((c) => c.status === status)
      if (search) list = list.filter((c) => c.title.includes(search))
      return void json(res, ok(paginate(list, page, size)))
    }
    p = match(pathname, '/evolution/candidates/:id')
    if (method === 'GET' && p) {
      const c = candidates.find((x) => x.id === p!.id)
      if (!c) return void json(res, fail(40401, '候选不存在'))
      return void json(res, ok(c))
    }
    // 状态迁移表：candidate → 验证/拒绝 → approved/rejected → 发布 → published → 回滚 → rolled_back
    const CANDIDATE_TRANSITIONS = {
      validate: { from: 'candidate', to: 'approved', verb: '验证' },
      publish: { from: 'approved', to: 'published', verb: '发布' },
      reject: { from: 'candidate', to: 'rejected', verb: '拒绝' },
      rollback: { from: 'published', to: 'rolled_back', verb: '回滚' },
    } as const
    for (const [action, spec] of Object.entries(CANDIDATE_TRANSITIONS)) {
      p = match(pathname, `/evolution/candidates/:id/${action}`)
      if (method === 'POST' && p) {
        const c = candidates.find((x) => x.id === p!.id)
        if (!c) return void json(res, fail(40401, '候选不存在'))
        if (c.status !== spec.from) return void json(res, fail(40020, `状态 ${c.status} 不允许${spec.verb}`))
        c.status = spec.to
        c.updated_at = isoDate(0)
        return void json(res, ok(c))
      }
    }

    /* ===== 会话 / 消息 ===== */
    if (method === 'GET' && pathname === '/conversations') {
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 20)
      const wsId = query.get('workspace_id')
      // 按工作区过滤；无参时排除工作区会话（/chat 全局列表不含工作区对话，M7-B）
      const mine = conversations.filter(
        (c) => c.user_id === user!.id && (wsId ? c.workspace_id === wsId : !c.workspace_id),
      )
      return void json(res, ok(paginate(mine, page, size)))
    }
    if (method === 'POST' && pathname === '/conversations') {
      const b = body.json ?? {}
      const nc = { id: uid('c'), user_id: user!.id, agent_id: DEFAULT_AGENT_ID, title: b.title ?? '新会话', status: 'active', max_messages: 1000, workspace_id: b.workspace_id ?? undefined, created_at: isoDate(0) }
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

    /* ===== 工作区（M7-B，docs/03 §5.14 / 交接板 2026-08-20） ===== */
    if (method === 'GET' && pathname === '/workspaces') {
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 20)
      const list = workspaces.filter((w) => w.status !== 'archived')
      return void json(res, ok(paginate(list, page, size)))
    }
    if (method === 'POST' && pathname === '/workspaces') {
      const b = body.json ?? {}
      const nw = {
        id: uid('ws'),
        org_id: user!.org_id ?? 'org_1',
        name: b.name ?? '未命名工作区',
        description: b.description ?? '',
        system_prompt_fragment: b.system_prompt_fragment ?? '',
        status: 'active',
        created_by: user!.id,
        created_at: isoDate(0),
      } as Workspace
      workspaces.unshift(nw)
      workspaceFiles[nw.id] = []
      return void json(res, ok(nw))
    }
    p = match(pathname, '/workspaces/:id')
    if (method === 'GET' && p) {
      const w = workspaces.find((x) => x.id === p!.id)
      if (!w) return void json(res, fail(40401, '工作区不存在'))
      return void json(res, ok(w))
    }
    if (method === 'PATCH' && p) {
      const w = workspaces.find((x) => x.id === p!.id)
      if (w) Object.assign(w, body.json)
      return void json(res, ok(w))
    }
    if (method === 'DELETE' && p) {
      // 硬删（交接板 2026-08-21 语义变更：归档→删除）：splice 工作区 + 级联清理文件树/内容/工作区会话/消息
      const idx = workspaces.findIndex((x) => x.id === p!.id)
      if (idx === -1) return void json(res, fail(40401, '工作区不存在'))
      workspaces.splice(idx, 1)
      delete workspaceFiles[p!.id]
      for (const k of Object.keys(workspaceFileContents)) if (k.startsWith(`${p!.id}|`)) delete workspaceFileContents[k]
      for (const c of [...conversations]) {
        if (c.workspace_id === p!.id) {
          conversations.splice(conversations.indexOf(c), 1)
          delete messages[c.id]
        }
      }
      return void json(res, ok(null))
    }
    /* 工作区文件（path 相对 root；空 path = 顶层，非空 = 直接子项） */
    p = match(pathname, '/workspaces/:id/files/content')
    if (method === 'GET' && p) {
      const path = query.get('path') ?? ''
      const content = workspaceFileContents[`${p!.id}|${path}`] ?? ''
      return void json(res, ok({ path, content: content.slice(0, 50_000) }))
    }
    p = match(pathname, '/workspaces/:id/files')
    if (method === 'GET' && p) {
      const path = query.get('path') ?? ''
      const files = workspaceFiles[p!.id] ?? []
      const children = files.filter((f) => {
        if (!path) return !f.path.includes('/')
        return f.path.startsWith(`${path}/`) && !f.path.slice(path.length + 1).includes('/')
      })
      if (p!.id === 'ws_001' && !ws001Injected) {
        ws001Injected = true
        setTimeout(() => {
          workspaceFiles['ws_001'].push({ name: '外部注入.md', path: '外部注入.md', is_dir: false, size: 64 })
          workspaceFileContents['ws_001|外部注入.md'] = '# 外部更新\n\n由 mock 模拟 agent 写入的新文件。\n'
        }, fast() ? 300 : 3000)
      }
      return void json(res, ok(children))
    }
    if (method === 'POST' && p) {
      const b = body.json ?? {}
      const path = String(b.path ?? '')
      if (!path) return void json(res, fail(40001, '缺少文件路径'))
      if (!workspaceFiles[p!.id]) workspaceFiles[p!.id] = []
      const list = workspaceFiles[p!.id]
      const existing = list.find((f) => f.path === path)
      if (b.is_dir) {
        // 新建文件夹（交接板 2026-08-21 契约，后端已实现 08-22）；幂等：已存在同名目录返回现有
        if (existing) {
          if (existing.is_dir) return void json(res, ok(existing))
          return void json(res, fail(40001, '目标路径已存在同名文件'))
        }
        list.push({ name: path.split('/').pop() ?? path, path, is_dir: true, size: 0 })
        return void json(res, ok({ name: path.split('/').pop(), path, is_dir: true, size: 0 }))
      }
      const content = String(b.content ?? '')
      if (existing && existing.is_dir) return void json(res, fail(40001, '目录不能写入内容'))
      if (!existing) list.push({ name: path.split('/').pop() ?? path, path, is_dir: false, size: content.length })
      workspaceFileContents[`${p!.id}|${path}`] = content
      return void json(res, ok({ name: path.split('/').pop(), path, is_dir: false, size: content.length }))
    }
    if (method === 'DELETE' && p) {
      const path = query.get('path') ?? ''
      if (!path) return void json(res, fail(40001, '缺少文件路径'))
      const list = workspaceFiles[p!.id] ?? []
      if (!list.some((f) => f.path === path)) return void json(res, fail(40401, '文件或目录不存在'))
      // 递归删除（目录：自身 + 子项前缀）+ 内容清理（交接板 2026-08-21）
      workspaceFiles[p!.id] = list.filter((f) => f.path !== path && !f.path.startsWith(`${path}/`))
      for (const k of Object.keys(workspaceFileContents)) {
        if (k.startsWith(`${p!.id}|${path}`)) delete workspaceFileContents[k]
      }
      return void json(res, ok(null))
    }
    /* 重命名文件/文件夹（交接板 2026-08-21 提案：子项前缀同步 + 内容 key 迁移） */
    p = match(pathname, '/workspaces/:id/files/rename')
    if (method === 'PATCH' && p) {
      const b = body.json ?? {}
      const oldPath = String(b.old_path ?? '')
      const newPath = String(b.new_path ?? '')
      if (!oldPath || !newPath || oldPath === newPath) return void json(res, fail(40001, '无效的重命名路径'))
      // 边界校验（对齐后端 08-22 契约）：跨出工作区 / 自身子路径 / 目标已存在
      if (newPath.split('/').includes('..')) return void json(res, fail(40001, '路径越界'))
      if (newPath.startsWith(`${oldPath}/`)) return void json(res, fail(40001, '不能移动到自身子路径'))
      const list = workspaceFiles[p!.id]
      if (!list || !list.some((f) => f.path === oldPath)) return void json(res, fail(40401, '文件或目录不存在'))
      if (list.some((f) => f.path === newPath)) return void json(res, fail(40302, '目标路径已存在'))
      for (const f of list) {
        if (f.path === oldPath || f.path.startsWith(`${oldPath}/`)) {
          const suffix = f.path.slice(oldPath.length)
          const oldFull = `${p!.id}|${f.path}`
          f.path = newPath + suffix
          f.name = f.path.split('/').pop() ?? f.path
          if (workspaceFileContents[oldFull]) {
            workspaceFileContents[`${p!.id}|${f.path}`] = workspaceFileContents[oldFull]
            delete workspaceFileContents[oldFull]
          }
        }
      }
      return void json(res, ok(null))
    }
    /* 打开本地文件夹（交接板 2026-08-21 契约，后端已实现 2f5c9e5；mock 返回成功） */
    p = match(pathname, '/workspaces/:id/reveal')
    if (method === 'POST' && p) {
      const w = workspaces.find((x) => x.id === p!.id)
      if (!w) return void json(res, fail(40401, '工作区不存在'))
      return void json(res, ok(null))
    }

    /* ===== 任务（仅中断恢复续流仍由 chat 使用；list/create/detail/events/cancel 已随任务页删除） ===== */
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
      // 排除元工具：tool_search 发现的是 domain 工具，不返回自身/其他 meta
      const hits = tools.filter((t) => !t.meta && (t.name.includes(q) || (t.description ?? '').toLowerCase().includes(q)))
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

    /* ===== Skills（M7-A 契约，交接板 2026-08-20：org 级、默认关闭、与工具同模式） ===== */
    if (method === 'GET' && pathname === '/skills') {
      const page = Number(query.get('page') ?? 1)
      const size = Number(query.get('page_size') ?? 20)
      return void json(res, ok(paginate(skills, page, size)))
    }
    if (method === 'POST' && pathname === '/skills') {
      const ns = {
        id: uid('sk'),
        org_id: currentUser(req)?.org_id ?? 'org_1',
        name: body.json?.name ?? `skill_${randHex(4)}`,
        description: body.json?.description ?? '',
        body: body.json?.body ?? '',
        source: 'manual',
        enabled: false,
        created_at: isoDate(0),
      } as Skill
      skills.unshift(ns)
      return void json(res, ok(ns))
    }
    if (method === 'POST' && pathname === '/skills/import') {
      const url = String(body.json?.url ?? '')
      const repo = url.split('/').filter(Boolean).pop()?.replace(/\.git$/, '') ?? `skill_${randHex(4)}`
      const ns = {
        id: uid('sk'),
        org_id: currentUser(req)?.org_id ?? 'org_1',
        name: repo,
        description: `git 导入技能（${url}）`,
        body: '> 由 git 导入，正文待后端 clone 后解析 SKILL.md（mock 演示）',
        source: 'git',
        enabled: false,
        created_at: isoDate(0),
      } as Skill
      skills.unshift(ns)
      return void json(res, ok(ns))
    }
    p = match(pathname, '/skills/:id')
    if (method === 'GET' && p) {
      const s = skills.find((x) => x.id === p!.id)
      if (!s) return void json(res, fail(40401, '技能不存在'))
      return void json(res, ok(s))
    }
    if (method === 'PATCH' && p) {
      const s = skills.find((x) => x.id === p!.id)
      if (s) Object.assign(s, body.json)
      return void json(res, ok(s))
    }
    if (method === 'DELETE' && p) {
      const idx = skills.findIndex((x) => x.id === p!.id)
      if (idx >= 0) skills.splice(idx, 1)
      return void json(res, ok(null))
    }

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
      const nd = { id: uid('kbd'), collection_id: p.id, name: file?.filename ?? '文档.md', mime_type: file?.mimeType ?? 'text/markdown', size: file?.size ?? 0, status: 'uploaded' as const, chunk_count: 0, progress: 0, created_at: isoDate(0) }
      kbDocuments.unshift(nd)
      simulateKbChain(nd)
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
        d.status = 'uploaded'
        d.progress = 0
        simulateKbChain(d)
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

    /* ===== Provider 配置（前端契约 docs/03 §5.6，后端已实现；mock 演示） ===== */
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
