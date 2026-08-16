import type { ApiEnvelope, User } from '@/types'

/** 随机 hex */
export function randHex(len = 8): string {
  let out = ''
  const chars = '0123456789abcdef'
  for (let i = 0; i < len; i++) out += chars[Math.floor(Math.random() * 16)]
  return out
}

/** mock 环境：所有 SSE 延迟是否归零（e2e 确定性）。由插件 configResolved 注入 */
let mockFast = false
export function setMockFast(v: boolean): void {
  mockFast = v
}
export function fast(): boolean {
  return mockFast
}

/** 模拟延迟（ms） */
export function delay(ms: number): number {
  return fast() ? 0 : ms
}

export function ok<T>(data: T): ApiEnvelope<T> {
  return { code: 0, message: 'ok', data, trace_id: `tr_${randHex(12)}` }
}

export function fail(code: number, message: string): ApiEnvelope<null> {
  return { code, message, data: null, trace_id: `tr_${randHex(12)}` }
}

export function json(res: import('http').ServerResponse, body: unknown, status = 200): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(body))
}

/** mock token 格式：`mock.<base64url(userJson)>`（Node 侧，用 Buffer 支持中文） */
export function signMockToken(user: Pick<User, 'id' | 'name' | 'role'>): string {
  return `mock.${Buffer.from(JSON.stringify(user)).toString('base64url')}`
}

export function decodeMockToken(token: string | undefined): Pick<User, 'id' | 'name' | 'role'> | null {
  if (!token?.startsWith('mock.')) return null
  try {
    const b64 = token.slice(5).replace(/-/g, '+').replace(/_/g, '/')
    const parsed = JSON.parse(Buffer.from(b64, 'base64').toString('utf-8'))
    if (parsed && parsed.id) return parsed
  } catch {
    /* ignore */
  }
  return null
}

export function isoDate(offsetMinutes: number): string {
  return new Date(Date.now() - offsetMinutes * 60_000).toISOString()
}

let seqCounter = 0
export function uid(prefix: string): string {
  seqCounter += 1
  return `${prefix}_${seqCounter}_${randHex(4)}`
}

export function paginate<T>(items: T[], page: number, page_size: number) {
  const start = (page - 1) * page_size
  return { items: items.slice(start, start + page_size), total: items.length, page, page_size }
}
