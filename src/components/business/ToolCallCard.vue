<script setup lang="ts">
import { computed, ref } from 'vue'
import { formatDuration } from '@/utils/format'
import JsonViewer from '@/components/common/JsonViewer.vue'

/** 工具调用卡（docs/02 §6.2）：默认只显示工具名 + 状态（紧凑行）；点「参数」展开可回放入参/输出/耗时。
 * 失败仅保留错误文案——重试由 agent/用户以语言发起，不由前端点击重试决定。 */
const props = defineProps<{
  toolName: string
  status?: string
  error?: string
  input?: unknown
  output?: unknown
  durationMs?: number
}>()

const isRunning = computed(() => props.status === 'running' || props.status === 'pending')
const isFailed = computed(() => props.status === 'error' || props.status === 'timeout' || props.status === 'failed')
const isCancelled = computed(() => props.status === 'cancelled')
const isAwaiting = computed(() => props.status === 'awaiting_confirm')

/** 有入参/输出任一即可展开回放 */
const hasParams = computed(() => props.input !== undefined || props.output !== undefined)
const expanded = ref(false)
function toggle(): void {
  expanded.value = !expanded.value
}

/** 简单值（null/string/number/boolean）用 pre 展示；对象/数组走 JsonViewer */
function isPrimitive(v: unknown): boolean {
  return v === null || v === undefined || ['string', 'number', 'boolean'].includes(typeof v)
}
function primitiveText(v: unknown): string {
  return v === null ? 'null' : String(v)
}
</script>

<template>
  <div class="tool-card" :class="{ running: isRunning, failed: isFailed }">
    <div class="tool-head">
      <span class="tool-icon"><el-icon><Cpu /></el-icon></span>
      <span class="tool-name">{{ toolName }}</span>
      <span v-if="isRunning" class="tool-spinner"><el-icon class="is-loading"><Loading /></el-icon>处理中</span>
      <span v-else-if="isAwaiting" class="tool-pending"><el-icon><Clock /></el-icon>待确认</span>
      <span v-else-if="isFailed" class="tool-fail"><el-icon><WarningFilled /></el-icon>{{ status === 'timeout' ? '超时' : '失败' }}</span>
      <span v-else-if="isCancelled" class="tool-cancel"><el-icon><RemoveFilled /></el-icon>已取消</span>
      <span v-else class="tool-ok"><el-icon><CircleCheckFilled /></el-icon>完成</span>
      <button
        v-if="hasParams"
        class="tool-toggle"
        type="button"
        :aria-expanded="expanded"
        @click="toggle"
      >
        <el-icon :size="12"><component :is="expanded ? 'ArrowUp' : 'ArrowDown'" /></el-icon>
        参数
      </button>
    </div>

    <div v-if="error || isFailed" class="tool-body">
      <div v-if="error" class="tool-error">{{ error }}</div>
    </div>

    <div v-if="expanded && hasParams" class="tool-body tool-params">
      <div v-if="input !== undefined" class="tool-param">
        <span class="tool-param-label">入参</span>
        <JsonViewer v-if="!isPrimitive(input)" :data="input" />
        <pre v-else class="tool-param-pre">{{ primitiveText(input) }}</pre>
      </div>
      <div v-if="output !== undefined" class="tool-param">
        <span class="tool-param-label">输出</span>
        <JsonViewer v-if="!isPrimitive(output)" :data="output" />
        <pre v-else class="tool-param-pre">{{ primitiveText(output) }}</pre>
      </div>
      <div v-if="durationMs != null" class="tool-param-dur">耗时 {{ formatDuration(durationMs) }}</div>
    </div>
  </div>
</template>

<style scoped>
/* 工具调用活动行（docs/02 §5.4.3）：紧凑行非气泡；失败仅保留错误文案（重试由 agent/用户语言发起） */
.tool-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  font-size: 12px;
  color: var(--app-text-secondary);
  line-height: 20px;
}
.tool-head {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.tool-icon {
  color: var(--app-primary);
  display: flex;
}
.tool-name {
  font-weight: 600;
  font-family: var(--app-font-mono);
  color: var(--app-text-secondary);
}
.tool-spinner,
.tool-pending,
.tool-fail,
.tool-cancel,
.tool-ok {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: var(--app-text-secondary);
}
.tool-pending {
  color: #f59e0b;
}
.tool-fail {
  color: #ef4444;
}
.tool-cancel {
  color: #6b7280;
}
.tool-ok {
  color: #16a34a;
}
.tool-toggle {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  border: none;
  background: transparent;
  color: var(--app-text-muted);
  font-size: 11px;
  cursor: pointer;
  padding: 0 2px;
}
.tool-toggle:hover {
  color: var(--app-primary);
}
.tool-body {
  max-width: 100%;
}
.tool-error {
  color: #ef4444;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.tool-params {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 4px;
}
.tool-param-label {
  font-size: 11px;
  color: var(--app-text-muted);
  margin-bottom: 2px;
}
.tool-param-pre {
  margin: 0;
  font-family: var(--app-font-mono);
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--app-bg);
  border: 1px solid var(--app-border-light);
  border-radius: 4px;
  padding: 4px 6px;
  max-height: 180px;
  overflow: auto;
  color: var(--app-text-secondary);
}
.tool-param-dur {
  font-size: 11px;
  color: var(--app-text-muted);
}
</style>
