<script setup lang="ts">
import { computed, nextTick, onUpdated, ref, watch } from 'vue'
import { renderMarkdown, splitStreamingCode } from '@/utils/markdown'

/**
 * MarkdownRenderer（docs/02 §5.4）：
 * - streaming=true：已完成部分渐进渲染 markdown（随行出现），末行（正在输入的 token）
 *   以纯文本 `.stream-tail` 显示（模板插值转义）——打字机效果 + 实时格式
 *   代码围栏内：stable 含未闭合围栏整段渲染成代码块；末行 tail 经 DOM 注入 `<code>` 元素内，
 *   不逃逸出块、不触发代码块整段重渲染（仅更新注入文本节点）。
 * - streaming=false：一次性走净化→GFM→高亮管线
 * 性能：仅当 stable（换行前已完成文本）变化时才重解析 markdown；token 帧只更新 tail。
 */
const props = defineProps<{ raw: string; streaming?: boolean }>()

const rootRef = ref<HTMLElement | null>(null)
let lastStable = ''
let stableHtml = ''
const parts = computed(() => {
  if (!props.streaming) return { html: renderMarkdown(props.raw), tail: '', inCode: false }
  const { stable, tail, inCode } = splitStreamingCode(props.raw)
  if (stable !== lastStable) {
    lastStable = stable
    stableHtml = renderMarkdown(stable)
  }
  return { html: stableHtml, tail, inCode }
})
const html = computed(() => parts.value.html)

/** 代码围栏内：把末行 tail 注入最后一个 <pre> code 元素内（转义文本节点，不重渲染代码块） */
function injectTail() {
  const root = rootRef.value
  if (!root || !parts.value.inCode) return
  const codes = root.querySelectorAll('pre > code')
  if (!codes.length) return
  const code = codes[codes.length - 1]
  code.querySelector('.stream-tail-code')?.remove()
  const span = document.createElement('span')
  span.className = 'stream-tail-code'
  span.textContent = parts.value.tail
  code.appendChild(span)
}

function attachCopyButtons() {
  const el = rootRef.value
  if (!el) return
  el.querySelectorAll('pre > code').forEach((code) => {
    const pre = code.parentElement
    if (!pre || pre.querySelector('.copy-btn')) return
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.className = 'copy-btn'
    btn.textContent = '复制'
    btn.addEventListener('click', () => {
      const text = code.textContent ?? ''
      if (navigator.clipboard?.writeText) {
        void navigator.clipboard.writeText(text).then(() => {
          btn.textContent = '已复制'
          setTimeout(() => (btn.textContent = '复制'), 1500)
        })
      }
    })
    pre.appendChild(btn)
  })
}

watch(
  () => [parts.value.html, parts.value.tail],
  () => {
    if (props.streaming) {
      void nextTick(() => {
        if (parts.value.inCode) injectTail()
      })
    }
  },
  { flush: 'post' },
)

watch(
  html,
  () => {
    if (!props.streaming) void nextTick(attachCopyButtons)
  },
  { immediate: true },
)

onUpdated(() => {
  if (!props.streaming) void nextTick(attachCopyButtons)
})
</script>

<template>
  <div class="stream-wrap">
    <div ref="rootRef" class="markdown-body" v-html="html" />
    <!-- 代码围栏内 tail 由 DOM 注入 code 元素；普通段走流式尾部纯文本 -->
    <span v-if="parts.tail && !parts.inCode" class="stream-tail">{{ parts.tail }}</span>
  </div>
</template>
