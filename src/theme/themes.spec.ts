import { describe, expect, it } from 'vitest'
import { DEFAULT_THEME, THEMES, applyTheme, getStoredTheme, getTheme } from './themes'

describe('themes（主题系统）', () => {
  function contrastRatio(foreground: string, background: string): number {
    const channel = (hex: string, offset: number) => parseInt(hex.slice(offset, offset + 2), 16) / 255
    const luminance = (hex: string) => {
      const rgb = [channel(hex, 1), channel(hex, 3), channel(hex, 5)].map((value) =>
        value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
      )
      return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722
    }
    const light = Math.max(luminance(foreground), luminance(background))
    const dark = Math.min(luminance(foreground), luminance(background))
    return (light + 0.05) / (dark + 0.05)
  }

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
      '--app-primary-fill',
      '--app-on-primary',
      '--app-link',
      '--app-focus-ring',
      '--app-success',
      '--app-warning',
      '--app-danger',
      '--app-info',
      '--app-text-tertiary',
      '--app-text-disabled',
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

  it('每套主题的操作填充色和链接色满足浅色内容区对比度', () => {
    for (const theme of THEMES) {
      expect(
        contrastRatio(theme.vars['--app-on-primary'], theme.vars['--app-primary-fill']),
        `${theme.id} primary fill 对比度不足`,
      ).toBeGreaterThanOrEqual(4.5)
      expect(
        contrastRatio(theme.vars['--app-link'], '#ffffff'),
        `${theme.id} link 对比度不足`,
      ).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('每套主题的侧栏普通文字和激活文字满足深浅背景对比度', () => {
    for (const theme of THEMES) {
      expect(
        contrastRatio(theme.vars['--app-sidebar-text'], theme.vars['--app-sidebar-bg']),
        `${theme.id} sidebar text 对比度不足`,
      ).toBeGreaterThanOrEqual(4.5)
      expect(
        contrastRatio(theme.vars['--app-sidebar-text-active'], theme.vars['--app-sidebar-bg']),
        `${theme.id} sidebar active text 对比度不足`,
      ).toBeGreaterThanOrEqual(4.5)
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
    expect(document.documentElement.style.getPropertyValue('--app-primary-fill')).toBeTruthy()
    expect(document.documentElement.style.getPropertyValue('--el-color-primary')).toBe(
      document.documentElement.style.getPropertyValue('--app-primary-fill'),
    )
    expect(getStoredTheme()).toBe(DEFAULT_THEME)
  })
})
