import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import {
  FEATURE,
  featureForUrl,
  isUnavailable,
  isUrlUnavailable,
  markUnavailable,
  markUnavailableForUrl,
  resetUnavailable,
} from './availability'
import { useTrajectoryStore } from '@/stores/trajectory'

describe('availability 路由映射', () => {
  it('已知缺失组 URL → 对应 feature（子路由更具体优先）', () => {
    expect(featureForUrl('/conversations/c1/trajectory')).toBe(FEATURE.trajectory)
    expect(featureForUrl('/notifications/stream')).toBe(FEATURE.notificationsStream)
    expect(featureForUrl('/notifications')).toBe(FEATURE.notifications)
    expect(featureForUrl('/notifications/123/read')).toBe(FEATURE.notifications)
    expect(featureForUrl('/users')).toBe(FEATURE.users)
    expect(featureForUrl('/system/logs/trace/t1')).toBe(FEATURE.systemTrace)
    expect(featureForUrl('/system/logs')).toBe(FEATURE.systemLogs)
    expect(featureForUrl('/system/evals/run')).toBe(FEATURE.systemEvals)
    expect(featureForUrl('/system/cost')).toBe(FEATURE.systemCost)
  })

  it('未知/既有路径 → null（不误标）', () => {
    expect(featureForUrl('/agents')).toBeNull()
    expect(featureForUrl('/chat/stream')).toBeNull()
    expect(featureForUrl('/conversations')).toBeNull()
  })

  it('绝对路径带 /api/v1 前缀也解析', () => {
    expect(featureForUrl('/api/v1/notifications/stream')).toBe(FEATURE.notificationsStream)
  })
})

describe('availability 打标', () => {
  beforeEach(() => resetUnavailable())

  it('mark/isUnavailable 与 URL 级封装', () => {
    expect(isUrlUnavailable('/users')).toBe(false)
    markUnavailableForUrl('/users')
    expect(isUnavailable(FEATURE.users)).toBe(true)
    expect(isUrlUnavailable('/users')).toBe(true)
    // 未标记组不受影响
    expect(isUrlUnavailable('/system/logs')).toBe(false)
  })

  it('markUnavailableForUrl 对未知路径静默（不误标）', () => {
    markUnavailableForUrl('/agents')
    expect(isUnavailable(FEATURE.users)).toBe(false)
    expect(isUnavailable(FEATURE.trajectory)).toBe(false)
  })

  it('reset 清空全部标记', () => {
    markUnavailable(FEATURE.systemCost)
    markUnavailableForUrl('/notifications')
    resetUnavailable()
    expect(isUnavailable(FEATURE.systemCost)).toBe(false)
    expect(isUnavailable(FEATURE.notifications)).toBe(false)
  })
})

describe('Pinia getter 反应式（读模块级 ref）', () => {
  beforeEach(() => {
    resetUnavailable()
    setActivePinia(createPinia())
  })

  it('trajectory store unavailable getter 随打标翻转', () => {
    const store = useTrajectoryStore()
    expect(store.unavailable).toBe(false)
    markUnavailable(FEATURE.trajectory)
    expect(store.unavailable).toBe(true)
  })
})
