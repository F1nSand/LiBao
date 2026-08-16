<script setup lang="ts">
import { ref } from 'vue'
import { useToolStore } from '@/stores/tool'
import type { ToolSearchHit } from '@/types'

/** 工具发现（docs/02 §6.2 H3 / docs/03 §5.5）：GET /tools/search?q= */
const store = useToolStore()
const keyword = ref('')
const results = ref<ToolSearchHit[]>([])
const searched = ref(false)
const loading = ref(false)

async function search() {
  const q = keyword.value.trim()
  if (!q) {
    results.value = []
    searched.value = false
    return
  }
  loading.value = true
  searched.value = true
  try {
    results.value = await store.search(q)
  } catch {
    // 接口失败 → 降级显示全量名称
    results.value = store.tools.map((t) => ({ id: t.id, name: t.name, description: t.description, enabled: t.enabled }))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="tool-search">
    <el-input
      v-model="keyword"
      size="small"
      placeholder="搜索工具…"
      clearable
      :prefix-icon="'Search'"
      @keyup.enter="search"
      @clear="results = []; searched = false"
    >
      <template #append>
        <el-button size="small" @click="search">搜索</el-button>
      </template>
    </el-input>

    <div v-if="searched" class="tool-search-result">
      <div v-if="loading">搜索中…</div>
      <div v-else-if="results.length === 0" class="search-empty">
        无匹配工具，可在工具列表创建
      </div>
      <div v-for="r in results" :key="r.id" class="search-item">
        <span class="search-name">{{ r.name }}</span>
        <span v-if="r.description" class="search-desc">{{ r.description }}</span>
        <el-tag :type="r.enabled ? 'success' : 'info'" size="small">{{ r.enabled ? '已启用' : '未启用' }}</el-tag>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-search-result {
  margin-top: 8px;
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius);
  padding: 8px;
  background: var(--app-content-bg);
}
.search-empty {
  color: var(--app-text-muted);
  font-size: 12px;
  text-align: center;
  padding: 8px 0;
}
.search-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
}
.search-name {
  font-weight: 600;
  font-family: var(--app-font-mono);
}
.search-desc {
  flex: 1;
  min-width: 0;
  color: var(--app-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
