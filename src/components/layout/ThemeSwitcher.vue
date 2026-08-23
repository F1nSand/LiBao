<script setup lang="ts">
import { ref } from 'vue'
import { THEMES, applyTheme, getStoredTheme, setStoredTheme } from '@/theme/themes'

/** 主题配色切换器（docs/02 §7）：TopBar 短袖图标按钮 → 气泡预设 9 套主题 */
const current = ref(getStoredTheme())
const active = ref(false)

function select(id: string) {
  applyTheme(id)
  setStoredTheme(id)
  current.value = id
  active.value = false
}
</script>

<template>
  <el-popover v-model:visible="active" trigger="click" placement="bottom-end" width="auto" :show-arrow="false" popper-class="theme-popover">
    <template #reference>
      <button class="theme-btn" type="button" title="主题配色" :class="{ active: active }">
        <!-- 小短袖图标（currentColor 与页面统一） -->
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 7.5 6.5 4.5h11L20 7.5l-3 2v10H7v-10z" />
          <path d="M9.5 9v3.5a2.5 2.5 0 0 0 5 0V9" />
        </svg>
      </button>
    </template>

    <div class="theme-popover-grid">
      <button
        v-for="t in THEMES"
        :key="t.id"
        class="theme-swatch"
        :class="{ active: t.id === current }"
        :title="t.name"
        @click="select(t.id)"
      >
        <span class="theme-swatch-preview">
          <span class="theme-swatch-primary" :style="{ background: t.preview.primary }" />
          <span class="theme-swatch-sidebar" :style="{ background: t.preview.sidebar }" />
        </span>
        <span class="theme-swatch-name">{{ t.name }}</span>
      </button>
    </div>
  </el-popover>
</template>

<style scoped>
.theme-btn {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--app-radius);
  color: var(--app-text-secondary);
  cursor: pointer;
}
.theme-btn:hover,
.theme-btn.active {
  border-color: var(--app-border);
  background: var(--app-bg);
  color: var(--app-text-main);
}
</style>

<!-- 气泡内容挂载到 body，需全局样式 -->
<style>
.theme-popover {
  padding: 8px;
}
.theme-popover-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(84px, 1fr));
  gap: 6px;
}
.theme-swatch {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 6px 4px;
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius);
  background: var(--app-content-bg);
  cursor: pointer;
}
.theme-swatch:hover {
  border-color: var(--app-primary);
}
.theme-swatch.active {
  border-color: var(--app-primary);
  outline: 2px solid var(--el-color-primary-light-8);
}
.theme-swatch-preview {
  display: flex;
  width: 100%;
  height: 20px;
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
  font-size: 11px;
  color: var(--app-text-secondary);
}
</style>
