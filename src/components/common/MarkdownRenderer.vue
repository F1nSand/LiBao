<script setup lang="ts">
import { computed, nextTick, onUpdated, ref, watch } from 'vue'
import { renderMarkdown, renderTextBare } from '@/utils/markdown'

/**
 * MarkdownRenderer（docs/02 §5.4）：
 * - streaming=true：裸文本（打字机预览，无 markdown 解析）
 * - streaming=false：一次性走净化→GFM→高亮管线
 */
const props = defineProps<{ raw: string; streaming?: boolean }>()

const rootRef = ref<HTMLElement | null>(null)
const html = computed(() => (props.streaming ? renderTextBare(props.raw) : renderMarkdown(props.raw)))

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
  <div ref="rootRef" class="markdown-body" :class="{ streaming }" v-html="html" />
</template>
