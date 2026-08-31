<script setup lang="ts">
import { THEMES, applyTheme, setStoredTheme } from '@/theme/themes'

/** 设置页「主题」pane（原 ThemeSwitcher 悬浮层改专门窗口）：
 *  受控组件——themeId 由 SettingsView 持有（tag 圆点同源），点选后 applyTheme + 持久化 + 上报。 */
defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [id: string] }>()

function select(id: string) {
  applyTheme(id)
  setStoredTheme(id)
  emit('update:modelValue', id)
}

function onSwatchKeydown(e: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return
  const current = e.currentTarget as HTMLElement
  const swatches = Array.from(current.parentElement?.querySelectorAll<HTMLElement>('.theme-swatch') ?? [])
  const position = swatches.indexOf(current)
  const columns = window.matchMedia('(max-width: 480px)').matches ? 2 : 3
  const delta = e.key === 'ArrowLeft' ? -1 : e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' ? -columns : columns
  const next = swatches[position + delta]
  if (!next) return
  e.preventDefault()
  next.focus()
}
</script>

<template>
  <div class="theme-pane">
    <div class="theme-pane-grid">
      <button
        v-for="t in THEMES"
        :key="t.id"
        type="button"
        class="theme-swatch"
        :class="{ active: t.id === modelValue }"
        :title="t.name"
        :aria-label="`选择主题：${t.name}`"
        :aria-pressed="t.id === modelValue"
        @click="select(t.id)"
        @keydown="onSwatchKeydown"
      >
        <span class="theme-swatch-preview">
          <span class="theme-swatch-primary" :style="{ background: t.preview.primary }" />
          <span class="theme-swatch-sidebar" :style="{ background: t.preview.sidebar }" />
        </span>
        <span class="theme-swatch-name">{{ t.name }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
/* pane 不 teleport（相对旧 ThemeSwitcher 不再需要非 scoped 全局块），全部 scoped */
.theme-pane {
  padding: 4px 0 0;
}
.theme-pane-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(96px, 1fr));
  gap: 8px;
}
.theme-swatch {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 6px;
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius);
  background: var(--app-content-bg);
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.15s var(--ease-out), transform 160ms var(--ease-out);
}
.theme-swatch:hover {
  border-color: var(--app-primary);
}
.theme-swatch.active {
  border-color: var(--app-primary);
  outline: 2px solid var(--el-color-primary-light-8);
}
.theme-swatch:active {
  transform: scale(0.97);
}
.theme-swatch-preview {
  display: flex;
  width: 100%;
  height: 22px;
  border-radius: var(--app-radius-sm);
  overflow: hidden;
}
.theme-swatch-primary {
  flex: 1;
}
.theme-swatch-sidebar {
  width: 34%;
}
.theme-swatch-name {
  font-size: var(--app-font-size-xs);
  color: var(--app-text-secondary);
}
@media (max-width: 480px) {
  .theme-pane-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .theme-swatch {
    min-height: var(--app-control-touch);
  }
}
</style>
