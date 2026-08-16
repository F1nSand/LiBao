import { describe, expect, it } from 'vitest'
import { DEFAULT_THEME, THEMES, applyTheme, getStoredTheme, getTheme } from './themes'

describe('themes（主题系统）', () => {
  it('9 套主题，id 唯一，默认主题存在', () => {
    expect(THEMES).toHaveLength(9)
    expect(new Set(THEMES.map((t) => t.id)).size).toBe(9)
    expect(getTheme(DEFAULT_THEME).id).toBe(DEFAULT_THEME)
    expect(THEMES.filter((t) => t.type === 'solid')).toHaveLength(6)
    expect(THEMES.filter((t) => t.type === 'contrast')).toHaveLength(3)
  })

  it('每套主题含必需 CSS 变量', () => {
    const required = [
      '--app-primary',
      '--el-color-primary',
      '--app-sidebar-bg',
      '--app-sidebar-conv-bg',
      '--app-sidebar-text',
      '--app-sidebar-text-active',
    ]
    for (const t of THEMES) {
      for (const k of required) expect(t.vars[k], `${t.id} 缺 ${k}`).toBeTruthy()
    }
  })

  it('纯色主题 conv-bg 与 sidebar-bg 不同（一深一浅）', () => {
    for (const t of THEMES.filter((x) => x.type === 'solid')) {
      expect(t.vars['--app-sidebar-conv-bg']).not.toBe(t.vars['--app-sidebar-bg'])
    }
  })

  it('applyTheme 写 :root 变量；getStoredTheme 默认靛蓝', () => {
    applyTheme('green')
    expect(document.documentElement.style.getPropertyValue('--app-primary')).toBe('#22c55e')
    expect(getStoredTheme()).toBe(DEFAULT_THEME)
  })
})
