import type { Router } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { onUnauthorized } from '@/api/http'
import type { Role } from '@/types'

export interface AccessMeta {
  requiresAuth?: boolean
  roles?: Role[]
}

/** 菜单过滤共用：按角色判定路由可访问性 */
export function canAccess(meta: AccessMeta | undefined, role: string | undefined): boolean {
  if (!meta?.requiresAuth) return true
  // 无角色限制 → 已登录即可访问（先于 role 判空，避免 user 未加载时的误拦截）
  if (!meta.roles || meta.roles.length === 0) return true
  if (!role) return false
  return meta.roles.includes(role as Role)
}

export function installGuard(router: Router): void {
  router.beforeEach(async (to) => {
    const auth = useAuthStore()
    // 刷新后首次导航前回填 token（App onMounted 的 hydrate 晚于守卫执行）
    if (auth.status === 'idle') await auth.hydrate()
    const meta = to.meta as AccessMeta | undefined

    // 未登录访问受保护页 → 登录页（带 redirect）
    if (meta?.requiresAuth && !auth.isAuthenticated) {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
    // 已登录访问登录页 → 首页
    if (to.path === '/login' && auth.isAuthenticated) {
      return { path: '/chat' }
    }
    // 角色守卫：user 未加载（刷新竞态，App onMounted hydrate 在途）时用 token 内角色兜底
    const role = auth.user?.role ?? auth.roleFromToken() ?? undefined
    if (meta?.requiresAuth && !canAccess(meta, role)) {
      return { path: '/chat' }
    }
    return true
  })

  // http 层 401 → 清会话并回登录页
  onUnauthorized(() => {
    const auth = useAuthStore()
    auth.resetAndRedirect()
  })
}
