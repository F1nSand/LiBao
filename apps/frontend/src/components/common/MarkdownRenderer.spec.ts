import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import MarkdownRenderer from './MarkdownRenderer.vue'

describe('MarkdownRenderer', () => {
  it('streaming=true 已完成部分渐进渲染 markdown，末行 tail 纯文本', () => {
    const w = mount(MarkdownRenderer, { props: { raw: '# 标题\n正文中', streaming: true } })
    expect(w.find('.markdown-body').html()).toContain('<h1>')
    expect(w.find('.stream-tail').text()).toBe('正文中')
  })

  it('streaming=true 无换行 → 全部为 tail（纯文本打字尾）', () => {
    const w = mount(MarkdownRenderer, { props: { raw: '# 标题', streaming: true } })
    expect(w.find('.stream-tail').text()).toBe('# 标题')
    expect(w.find('.markdown-body').html()).not.toContain('<h1')
  })

  it('streaming=false 渲染 markdown，无 tail', () => {
    const w = mount(MarkdownRenderer, { props: { raw: '# 标题', streaming: false } })
    expect(w.html()).toContain('<h1')
    expect(w.find('.stream-tail').exists()).toBe(false)
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
