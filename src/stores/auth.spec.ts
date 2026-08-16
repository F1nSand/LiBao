import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { login, logout, me } = vi.hoisted(() => ({
  login: vi.fn(),
  logout: vi.fn(),
  me: vi.fn(),
}))

vi.mock('@/api/auth', () => ({ login, logout, me }))

import { useAuthStore } from './auth'

const TOKEN_KEY = 'agent.auth.token'

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  localStorage.clear()
})

describe('auth store', () => {
  it('login 成功写入 token/user 并持久化', async () => {
    login.mockResolvedValue({
      token: 't1',
      user: { id: 'u1', name: '管理员', role: 'admin' },
    })
    const store = useAuthStore()
    await store.login('admin', 'admin123')
    expect(store.token).toBe('t1')
    expect(store.user?.role).toBe('admin')
    expect(localStorage.getItem(TOKEN_KEY)).toBe('t1')
    expect(store.isAuthenticated).toBe(true)
    expect(store.isAdmin).toBe(true)
  })

  it('hydrate：有 token 时校验 me()', async () => {
    localStorage.setItem(TOKEN_KEY, 't1')
    me.mockResolvedValue({ id: 'u1', name: '访客', role: 'viewer' })
    const store = useAuthStore()
    await store.hydrate()
    expect(store.user?.role).toBe('viewer')
    expect(store.status).toBe('ready')
  })

  it('hydrate：token 失效时清空本地', async () => {
    localStorage.setItem(TOKEN_KEY, 'bad-token')
    me.mockRejectedValue(new Error('401'))
    const store = useAuthStore()
    await store.hydrate()
    expect(store.token).toBeNull()
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  })

  it('logout 清空会话', async () => {
    logout.mockResolvedValue(null)
    const store = useAuthStore()
    store.token = 't1'
    store.user = { id: 'u1', name: 'A', role: 'admin' }
    await store.logout()
    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  })
})
