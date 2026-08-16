import { defineStore } from 'pinia'
import { login as apiLogin, logout as apiLogout, me as apiMe } from '@/api/auth'
import { setAuthToken } from '@/api/http'
import { getToken, setToken, clearToken, parseRole } from '@/utils/token'
import type { Role, User } from '@/types'

interface AuthState {
  token: string | null
  user: User | null
  status: 'idle' | 'loading' | 'ready'
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    token: null,
    user: null,
    status: 'idle',
  }),
  getters: {
    isAuthenticated: (s) => !!s.token,
    isAdmin: (s) => s.user?.role === 'admin',
    isDeveloper: (s) => s.user?.role === 'admin' || s.user?.role === 'developer',
    role: (s): Role | undefined => s.user?.role,
  },
  actions: {
    /** 启动时回填：localStorage 有 token → 校验 me()，失败清空 */
    async hydrate() {
      const token = getToken()
      if (!token) {
        this.status = 'ready'
        return
      }
      this.token = token
      setAuthToken(token)
      this.status = 'loading'
      try {
        this.user = await apiMe()
        this.status = 'ready'
      } catch {
        // token 失效：清空本地
        this.token = null
        this.user = null
        clearToken()
        setAuthToken(null)
        this.status = 'ready'
      }
    },

    async login(username: string, password: string) {
      const res = await apiLogin({ username, password })
      this.token = res.token
      this.user = res.user
      this.status = 'ready'
      setToken(res.token)
      setAuthToken(res.token)
    },

    async logout() {
      try {
        await apiLogout()
      } catch {
        // 登出接口失败也清本地会话
      } finally {
        this.token = null
        this.user = null
        clearToken()
        setAuthToken(null)
      }
    },

    async fetchMe() {
      this.user = await apiMe()
    },

    /** 401 联动：清会话并回登录页 */
    resetAndRedirect() {
      this.token = null
      this.user = null
      clearToken()
      setAuthToken(null)
      // 避免 import 循环，这里动态取 router
      import('@/router').then(({ router }) => router.replace('/login'))
    },

    /** 角色兜底：token 有效但 user 未加载时用 token 内 role */
    roleFromToken(): Role | null {
      return this.token ? parseRole(this.token) : null
    },
  },
})
