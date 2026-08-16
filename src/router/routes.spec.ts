import { describe, expect, it } from 'vitest'
import { isSettingsRoute, SETTINGS_ROUTES, menuItems } from './routes'

describe('isSettingsRoute（设置组路由）', () => {
  it('设置组内路由 → true', () => {
    for (const p of SETTINGS_ROUTES) expect(isSettingsRoute(p)).toBe(true)
  })
  it('非设置组路由 → false', () => {
    expect(isSettingsRoute('/chat')).toBe(false)
    expect(isSettingsRoute('/agents')).toBe(false)
    expect(isSettingsRoute('/kb')).toBe(false)
    expect(isSettingsRoute('/trajectory/c_001')).toBe(false)
  })
})

describe('menuItems（层级）', () => {
  it('工作区在对话上方（顶部顺序 = /workspace → /chat）', () => {
    expect(menuItems.slice(0, 2).map((i) => i.path)).toEqual(['/workspace', '/chat'])
  })

  it('设置项带 children（任务/工具/记忆/系统/设置）', () => {
    const settings = menuItems.find((i) => i.path === '/settings')
    expect(settings?.children?.map((c) => c.path)).toEqual([
      '/settings',
      '/tasks',
      '/tools',
      '/memory',
      '/system',
    ])
  })
})
