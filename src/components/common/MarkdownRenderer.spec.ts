import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MarkdownRenderer from './MarkdownRenderer.vue'

describe('MarkdownRenderer', () => {
  it('streaming=true 渲染裸文本（不解析 markdown）', () => {
    const w = mount(MarkdownRenderer, { props: { raw: '# 标题', streaming: true } })
    expect(w.html()).toContain('# 标题')
    expect(w.html()).not.toContain('<h1')
  })

  it('streaming=false 渲染 markdown', () => {
    const w = mount(MarkdownRenderer, { props: { raw: '# 标题', streaming: false } })
    expect(w.html()).toContain('<h1')
  })

  it('空内容兜底不崩', () => {
    const w = mount(MarkdownRenderer, { props: { raw: '', streaming: false } })
    expect(w.exists()).toBe(true)
  })

  it('危险 HTML 被净化', () => {
    const w = mount(MarkdownRenderer, { props: { raw: '<script>alert(1)</script>', streaming: false } })
    expect(w.html()).not.toContain('<script>')
  })
})
