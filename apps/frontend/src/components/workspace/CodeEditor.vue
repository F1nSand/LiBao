<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import hljs from 'highlight.js'

/**
 * 工作区文件预览/编辑代码编辑器（《02》前端设计 §4）：
 * 透明 textarea 覆盖 hljs 高亮 pre + 行号 gutter + 共享滚动容器（gutter sticky + pre 流内撑高 +
 * textarea absolute 覆盖）→ 零 JS 滚动同步。
 * 关键：gutter/pre/textarea 的对齐矩阵（padding/font/line-height/tab-size/white-space）必须逐字符一致。
 */
const props = defineProps<{
  modelValue: string
  language?: string
  placeholder?: string
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  focus: []
  blur: []
  save: []
}>()

/** 超限跳过高亮（超大文件用 textContent，保性能） */
const MAX_HIGHLIGHT_CHARS = 200_000

const codeEl = ref<HTMLElement>()
const taEl = ref<HTMLTextAreaElement>()
const composing = ref(false)
let hlTimer: ReturnType<typeof setTimeout> | null = null

/** 行号（与 pre 行数严格对齐：join '\n' 无尾部空行）；gutter 用 white-space:pre 逐行对齐 */
const gutterText = computed(() => {
  const n = props.modelValue.split('\n').length
  const lines: string[] = []
  for (let i = 1; i <= n; i++) lines.push(String(i))
  return lines.join('\n')
})

/** 高亮渲染：按 language 映射；未知/空串 highlightAuto 兜底；超限直接文本 */
function renderHighlight() {
  const code = props.modelValue
  if (!codeEl.value) return
  if (code.length > MAX_HIGHLIGHT_CHARS) {
    codeEl.value.textContent = code
    return
  }
  try {
    const lang = props.language && hljs.getLanguage(props.language) ? props.language : ''
    codeEl.value.innerHTML = lang
      ? hljs.highlight(code, { language: lang }).value
      : hljs.highlightAuto(code).value
  } catch {
    codeEl.value.textContent = code
  }
}

/** 初始渲染在 onMounted（watch 立即执行时 codeEl 未挂载）；变更走 120ms 防抖 */
onMounted(renderHighlight)
watch(
  () => props.modelValue,
  () => {
    if (hlTimer) clearTimeout(hlTimer)
    hlTimer = setTimeout(renderHighlight, 120)
  },
)

onBeforeUnmount(() => {
  if (hlTimer) clearTimeout(hlTimer)
})

function onInput(e: Event) {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}

function onKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault()
    emit('save')
    return
  }
  if (e.key === 'Tab') {
    e.preventDefault()
    insertText('  ')
  }
}

/** Tab → 插入两空格（保留 caret 位置，rAF 恢复选区） */
function insertText(text: string) {
  const ta = taEl.value
  if (!ta) return
  const start = ta.selectionStart
  const end = ta.selectionEnd
  const next = props.modelValue.slice(0, start) + text + props.modelValue.slice(end)
  emit('update:modelValue', next)
  requestAnimationFrame(() => {
    ta.selectionStart = ta.selectionEnd = start + text.length
  })
}
</script>

<template>
  <div class="ce-wrap">
    <div class="ce-scroll">
      <div class="ce-inner">
        <div class="ce-gutter" aria-hidden="true">{{ gutterText }}</div>
        <div class="ce-body">
          <pre class="ce-pre"><code ref="codeEl" class="hljs"></code></pre>
          <textarea
            ref="taEl"
            class="ce-ta"
            :value="props.modelValue"
            wrap="off"
            spellcheck="false"
            autocomplete="off"
            autocapitalize="off"
            :placeholder="props.placeholder"
            :class="{ 'is-composing': composing }"
            @input="onInput"
            @focus="emit('focus')"
            @blur="emit('blur')"
            @keydown="onKeydown"
            @compositionstart="composing = true"
            @compositionend="composing = false"
          ></textarea>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ce-wrap {
  position: relative;
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius);
  overflow: hidden;
}
.ce-wrap:focus-within {
  border-color: var(--app-primary);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--app-primary) 18%, transparent);
}
.ce-scroll {
  overflow: auto;
  max-height: 420px;
}
.ce-inner {
  display: flex;
  align-items: flex-start;
  width: max-content;
  min-width: 100%;
}
.ce-gutter {
  position: sticky;
  left: 0;
  z-index: 1;
  flex-shrink: 0;
  min-width: 44px;
  padding: 12px 8px;
  text-align: right;
  user-select: none;
  background: var(--app-bg);
  border-right: 1px solid var(--app-border-light);
  color: var(--app-text-muted);
  font-family: var(--app-font-mono);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre;
}
.ce-body {
  position: relative;
  flex: 1;
  min-width: max-content;
}
.ce-pre {
  margin: 0;
  padding: 12px 16px;
  font-family: var(--app-font-mono);
  font-size: 13px;
  line-height: 1.6;
  tab-size: 2;
  white-space: pre;
  word-break: normal;
  overflow-wrap: normal;
}
.ce-pre code {
  display: block;
  font-family: inherit;
  font-size: inherit;
  line-height: inherit;
  background: transparent;
  padding: 0;
}
.ce-ta {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  padding: 12px 16px;
  font-family: var(--app-font-mono);
  font-size: 13px;
  line-height: 1.6;
  tab-size: 2;
  white-space: pre;
  word-break: normal;
  overflow-wrap: normal;
  overflow: hidden;
  resize: none;
  border: none;
  outline: none;
  background: transparent;
  color: transparent;
  caret-color: var(--app-text-main);
  z-index: 2;
}
/* 选区可见：半透明主色底 + 文字仍透明（透出下方高亮） */
.ce-ta::selection {
  background: color-mix(in srgb, var(--app-primary) 25%, transparent);
  color: transparent;
}
/* CJK 输入法组合期显示真实文字（透明文字在 composition 期看不见） */
.ce-ta.is-composing {
  color: var(--app-text-main);
}
</style>
