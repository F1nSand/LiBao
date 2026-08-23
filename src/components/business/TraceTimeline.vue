<script setup lang="ts">
import { ref, watch } from 'vue'
import { useSystemStore } from '@/stores/system'
import { swallowNotImplemented } from '@/utils/http-envelope'
import type { TraceDetail, TraceEvent } from '@/types'
import JsonViewer from '@/components/common/JsonViewer.vue'
import EmptyState from '@/components/common/EmptyState.vue'

/** trace 全链路时间线（docs/02 §6.2 / docs/03 §5.8）：LLM/工具/检索/节点分色 */
const props = defineProps<{ traceId: string | null }>()

const store = useSystemStore()
const detail = ref<TraceDetail | null>(null)
const loading = ref(false)
const expanded = ref<number | null>(null)
const unavailable = ref(false)
const loadFailed = ref(false)

const NODE_META: Record<string, { label: string; color: string }> = {
  llm: { label: 'LLM', color: '#6366f1' },
  tool: { label: '工具', color: '#f59e0b' },
  retrieval: { label: '检索', color: '#22c55e' },
  router: { label: '节点', color: '#8b5cf6' },
}

async function load() {
  if (!props.traceId) return
  loading.value = true
  try {
    const res = await swallowNotImplemented(store.trace(props.traceId))
    detail.value = res ?? null
    unavailable.value = res === undefined
    loadFailed.value = false
  } catch {
    detail.value = null
    unavailable.value = false
    loadFailed.value = true
  } finally {
    loading.value = false
  }
}

watch(() => props.traceId, load, { immediate: true })

function meta(ev: TraceEvent) {
  return NODE_META[ev.node_type] ?? { label: ev.node_type, color: '#6b7280' }
}
</script>

<template>
  <div v-loading="loading" class="timeline">
    <div class="trace-id mono">trace: {{ props.traceId }}</div>
    <div v-if="detail" class="timeline-list">
      <div v-for="(ev, i) in detail.events" :key="i" class="tl-item">
        <div class="tl-rail">
          <span class="tl-dot" :style="{ background: meta(ev).color }" />
          <span v-if="i < detail.events.length - 1" class="tl-line" :style="{ background: meta(ev).color }" />
        </div>
        <div class="tl-body">
          <div class="tl-head" @click="expanded = expanded === i ? null : i">
            <span class="tl-node" :style="{ color: meta(ev).color }">{{ meta(ev).label }}</span>
            <span class="tl-name">{{ ev.name }}</span>
            <span class="tl-status" :class="ev.status">{{ ev.status }}</span>
            <span v-if="ev.duration_ms != null" class="tl-duration">{{ ev.duration_ms }}ms</span>
          </div>
          <div v-if="ev.token_usage?.total_tokens" class="tl-tokens">{{ ev.token_usage.total_tokens }} tokens</div>
          <div v-if="expanded === i" class="tl-detail">
            <div v-if="ev.input !== undefined"><div class="tl-label">输入</div><JsonViewer :data="ev.input" /></div>
            <div v-if="ev.output !== undefined"><div class="tl-label">输出</div><JsonViewer :data="ev.output" /></div>
          </div>
        </div>
      </div>
    </div>
    <EmptyState v-else-if="unavailable" text="后端暂未实现 trace 接口" />
    <el-empty v-else-if="loadFailed" description="trace 加载失败" :image-size="60" />
    <el-empty v-else description="点击日志行查看 trace" :image-size="60" />
  </div>
</template>

<style scoped>
.timeline {
  padding: 4px;
}
.trace-id {
  color: var(--app-text-muted);
  font-size: 12px;
  margin-bottom: 10px;
}
.tl-item {
  display: flex;
  gap: 10px;
}
.tl-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 12px;
  flex-shrink: 0;
}
.tl-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-top: 4px;
  flex-shrink: 0;
}
.tl-line {
  flex: 1;
  width: 2px;
  margin: 2px 0;
}
.tl-body {
  flex: 1;
  min-width: 0;
  padding-bottom: 14px;
}
.tl-head {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 13px;
  border-radius: var(--app-radius);
  transition: background 0.15s;
}
.tl-head:hover {
  background: var(--app-bg);
}
.tl-node {
  font-weight: 600;
  font-size: 12px;
}
.tl-status {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
}
.tl-status.success {
  background: #ecfdf3;
  color: #16a34a;
}
.tl-status.failed {
  background: #fef2f2;
  color: #ef4444;
}
.tl-duration {
  margin-left: auto;
  font-size: 12px;
  color: var(--app-text-muted);
  font-family: var(--app-font-mono);
}
.tl-tokens {
  font-size: 11px;
  color: var(--app-text-muted);
}
.tl-detail {
  margin-top: 6px;
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius-sm);
  padding: 6px;
  background: var(--app-bg);
  max-height: 200px;
  overflow: auto;
}
.tl-label {
  font-size: 11px;
  color: var(--app-text-muted);
}
.mono {
  font-family: var(--app-font-mono);
}
</style>
