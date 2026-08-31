import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const tokens = readFileSync('src/styles/tokens.css', 'utf8')

describe('全局设计令牌', () => {
  it('声明语义颜色、间距、控件尺寸和层级令牌', () => {
    const required = [
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
      '--app-space-1',
      '--app-space-6',
      '--app-control-sm',
      '--app-control-md',
      '--app-control-touch',
      '--app-z-dropdown',
      '--app-z-modal',
      '--app-z-toast',
    ]

    for (const token of required) expect(tokens, `缺少 ${token}`).toContain(token)
  })

  it('状态颜色和 disabled 颜色不依赖未定义 fallback', () => {
    expect(tokens).toContain('--app-text-muted:')
    expect(tokens).toContain('--app-text-disabled:')
    expect(tokens).not.toContain('var(--app-text-disabled,')
  })
})
