<script setup lang="ts">
import { computed, nextTick, onUpdated, ref, watch } from 'vue'
import { renderMarkdown, splitStreamingText } from '@/utils/markdown'

/**
 * MarkdownRenderer（docs/02 §5.4）：
 * - streaming=true：已完成部分渐进渲染 markdown（随行出现），末行（正在输入的 token）
 *   以纯文本 `.stream-tail` 显示（模板插值转义）——打字机效果 + 实时格式
 * - streaming=false：一次性走净化→GFM→高亮管线
 * 性能：仅当 stable（换行前已完成文本）变化时才重解析 markdown；token 帧只更新 tail 纯文本。
 */
const props = defineProps<{ raw: string; streaming?: boolean }>()

const rootRef = ref<HTMLElement | null>(null)
let lastStable = ''
let stableHtml = ''
const parts = computed(() => {
  if (!props.streaming) return { html: renderMarkdown(props.raw), tail: '' }
  const { stable, tail } = splitStreamingText(props.raw)
  if (stable !== lastStable) {
    lastStable = stable
    stableHtml = renderMarkdown(stable)
  }
  return { html: stableHtml, tail }
})
const html = computed(() => parts.value.html)

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
    <span v-if="parts.tail" class="stream-tail">{{ parts.tail }}</span>
  </div>
</template>
