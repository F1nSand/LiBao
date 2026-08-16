import type { Role } from '@/types'

const TOKEN_KEY = 'agent.auth.token'

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

/** 从 JWT payload 解析角色（守卫用；解析失败返回 null） */
export function parseRole(token: string): Role | null {
  try {
    const payloadPart = token.split('.')[1]
    if (!payloadPart) return null
    const payload = JSON.parse(atob(payloadPart.replace(/-/g, '+').replace(/_/g, '/')))
    const role: unknown = payload?.role
    return role === 'admin' || role === 'developer' || role === 'viewer' ? role : null
  } catch {
    return null
  }
}
