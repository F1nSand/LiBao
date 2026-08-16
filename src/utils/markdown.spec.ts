import { describe, it, expect } from 'vitest'
import { renderMarkdown, renderTextBare, MARKDOWN_WHITELIST } from './markdown'

describe('renderMarkdown 管线', () => {
  it('GFM 表格渲染为 table', () => {
    const html = renderMarkdown('| a | b |\n|---|---|\n| 1 | 2 |')
    expect(html).toContain('<table>')
    expect(html).toContain('<th>a</th>')
  })

  it('任务列表渲染 checkbox', () => {
    const html = renderMarkdown('- [x] 已完成\n- [ ] 未完成')
    expect(html).toContain('type="checkbox"')
    expect(html).toContain('checked')
  })

  it('代码块语法高亮', () => {
    const html = renderMarkdown('```js\nconst a = 1\n```')
    expect(html).toContain('language-js')
    expect(html).toContain('<code class="language-js">')
  })

  it('不支持的代码语言降级为纯文本，不抛错', () => {
    const html = renderMarkdown('```nosuchlang\n<foo>\n```')
    expect(html).toContain('<code')
    expect(html).not.toContain('<foo>')
  })

  it('超长行容错解析不崩', () => {
    const long = 'x'.repeat(20_000)
    const html = renderMarkdown(long)
    expect(html.length).toBeGreaterThan(0)
  })
})

describe('XSS 防护', () => {
  it('script 标签被净化', () => {
    const html = renderMarkdown('<script>alert(1)</script>')
    expect(html).not.toContain('<script>')
  })

  it('事件属性被移除（raw HTML 被转义为文本，无活动属性）', () => {
    const html = renderMarkdown('<img src=x onerror=alert(1)>')
    expect(html).not.toContain('<img') // 无原始 img 标签
    expect(html).toContain('&lt;img') // 以转义文本形式呈现
  })

  it('javascript: 协议链接不产生可点击 href', () => {
    const html = renderMarkdown('[x](javascript:alert(1))')
    expect(html).not.toContain('href="javascript')
    expect(html).not.toContain('href=\'javascript')
  })

  it('iframe 被移除（转义为文本）', () => {
    const html = renderMarkdown('<iframe src="https://evil"></iframe>')
    expect(html).not.toContain('<iframe')
  })

  it('代码块内的原始 HTML 保持文本不执行', () => {
    const html = renderMarkdown('```html\n<script>alert(1)</script>\n```')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<script>alert(1)</script>')
    expect(html).toContain('&lt;') // 尖括号被转义
  })

  it('合法链接保留且带 noopener', () => {
    const html = renderMarkdown('[ok](https://example.com)')
    expect(html).toContain('https://example.com')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
  })
})

describe('renderTextBare 流式裸文本', () => {
  it('HTML 转义但不解析 markdown', () => {
    expect(renderTextBare('<script>').toLowerCase()).toContain('&lt;script&gt;')
  })
})

describe('白名单', () => {
  it('拒绝 script/iframe/onerror', () => {
    expect(MARKDOWN_WHITELIST.tags).not.toContain('script')
    expect(MARKDOWN_WHITELIST.tags).not.toContain('iframe')
    expect(MARKDOWN_WHITELIST.attrs).not.toContain('onerror')
  })
})
