<script setup lang="ts">
import { computed, ref } from 'vue'
import { THEMES, applyTheme, getStoredTheme, setStoredTheme } from '@/theme/themes'

/** 主题配色切换器（docs/02 §7）：设置页「主题」tag → 气泡预设 9 套主题 */
const current = ref(getStoredTheme())
const active = ref(false)
const currentPrimary = computed(() => THEMES.find((t) => t.id === current.value)?.preview.primary ?? '')

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
      <button class="theme-tag" type="button" title="主题配色" :class="{ active: active }">
        <span class="theme-tag-dot" :style="{ background: currentPrimary }" />
        <span>主题</span>
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
.theme-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: var(--app-radius);
  border: 1px solid var(--app-border-light);
  background: var(--app-content-bg);
  font-size: var(--app-font-size-sm);
  color: var(--app-text-secondary);
  cursor: pointer;
  transition: border-color 0.2s var(--ease-out), color 0.2s var(--ease-out);
}
.theme-tag:hover,
.theme-tag.active {
  border-color: var(--app-primary);
  color: var(--app-primary);
}
.theme-tag-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1px solid var(--app-border-light);
  flex-shrink: 0;
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
