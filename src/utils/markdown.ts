import MarkdownIt from 'markdown-it'
import taskLists from 'markdown-it-task-lists'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'

/**
 * Markdown 渲染管线（docs/02 §5.4，固定顺序不可跳步）：
 *   markdown-it 解析(GFM, html:false) → highlight.js 代码高亮 → DOMPurify 白名单净化 → DOM
 * LLM 输出一律视为不可信内容。
 */

/** 净化白名单（导出供单测断言） */
export const MARKDOWN_WHITELIST = {
  tags: [
    'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'strong', 'em', 'del',
    'code', 'pre', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'a', 'img', 'hr', 'input', 'span', 'div', 'br',
  ],
  attrs: ['href', 'title', 'target', 'rel', 'src', 'alt', 'lang', 'class', 'checked', 'disabled', 'type'],
  uri: /^(?:https?:|mailto:|tel:|data:image\/)/i,
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code class="language-${lang}">${hljs.highlight(code, { language: lang }).value}</code></pre>`
      } catch {
        /* 高亮失败降级纯文本 */
      }
    }
    // 语言不支持 → 保留语言标识的纯文本代码块（docs/02 §5.4.1 异常路径）
    return `<pre class="hljs"><code class="language-${lang ?? ''}">${escapeHtml(code)}</code></pre>`
  },
})
md.use(taskLists, { enabled: false, label: true })

/** 渲染管线唯一入口：返回净化后的 HTML（可安全 v-html） */
export function renderMarkdown(src: string): string {
  if (!src) return ''
  const rendered = md.render(src)
  const clean = DOMPurify.sanitize(rendered, {
    ALLOWED_TAGS: MARKDOWN_WHITELIST.tags,
    ALLOWED_ATTR: MARKDOWN_WHITELIST.attrs,
    ALLOWED_URI_REGEXP: MARKDOWN_WHITELIST.uri,
  })
  if (!clean.trim()) return escapeHtml(src) // 净化后为空 → 原始文本兜底（docs/02 §5.4.1）
  // 净化后安全后处理：链接新窗口 + noopener（防 tabnabbing）；任务列表 checkbox 补 type
  return clean
    .replace(/<a\s(?![^>]*target=)/g, '<a target="_blank" rel="noopener noreferrer" ')
    .replace(/<input\s(?![^>]*type=)/g, '<input type="checkbox" ')
}

/** 流式拆分（docs/02 §5.4.1）：stable = 最后一个换行前的已完成文本；tail = 末行局部（正在输入的 token）。
 * 流式期对 stable 做 markdown 渲染（随行渐进），tail 保持纯文本——避免半个词/未闭合块被打断。 */
export function splitStreamingText(raw: string): { stable: string; tail: string } {
  const idx = raw.lastIndexOf('\n')
  if (idx === -1) return { stable: '', tail: raw }
  return { stable: raw.slice(0, idx + 1), tail: raw.slice(idx + 1) }
}

/** 流式渲染：stable 走 markdown 管线；tail 为原始末行（模板插值自动转义，安全模型不变） */
export function renderStreamingMarkdown(raw: string): { html: string; tail: string } {
  const { stable, tail } = splitStreamingText(raw)
  return { html: renderMarkdown(stable), tail }
}
