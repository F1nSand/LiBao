<script setup lang="ts">
import { computed, ref } from 'vue'
import { formatDuration, toolCallPreview } from '@/utils/format'
import JsonViewer from '@/components/common/JsonViewer.vue'

/** 工具调用活动行（docs/02 §5.4.3）：无外框平铺行——默认收起只显示单行摘要预览，
 * hover 行左侧出现三角，整行点击展开详情（入参/输出/耗时，轻量代码块无卡片边框）。
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
const hover = ref(false)
function toggle(): void {
  expanded.value = !expanded.value
}

/** 收起预览：`工具标识 · 摘要`（Write→路径 / 更新任务清单→状态 / 其它→入参） */
const preview = computed(() => toolCallPreview(props.toolName, props.input))

/** 简单值（null/string/number/boolean）用 pre 展示；对象/数组走 JsonViewer */
function isPrimitive(v: unknown): boolean {
  return v === null || v === undefined || ['string', 'number', 'boolean'].includes(typeof v)
}
function primitiveText(v: unknown): string {
  return v === null ? 'null' : String(v)
}
</script>

<template>
  <div class="tool-row">
    <div
      class="tool-row-head"
      :class="{ running: isRunning, failed: isFailed }"
      role="button"
      :aria-expanded="expanded"
      @click="toggle"
      @mouseenter="hover = true"
      @mouseleave="hover = false"
    >
      <!-- hover 才出现的展开/收起三角 -->
      <span v-show="hover" class="tool-arrow">
        <el-icon :size="12"><component :is="expanded ? 'ArrowDown' : 'ArrowRight'" /></el-icon>
      </span>
      <span class="tool-summary">{{ preview }}</span>
      <span v-if="isRunning" class="tool-status running">处理中</span>
      <span v-else-if="isAwaiting" class="tool-status awaiting">待确认</span>
      <span v-else-if="isFailed" class="tool-status failed">{{ status === 'timeout' ? '超时' : '失败' }}</span>
      <span v-else-if="isCancelled" class="tool-status cancelled">已取消</span>
      <span v-else class="tool-status ok">完成</span>
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
/* 工具调用活动行：无外框平铺（非气泡），字号小于正文、弱化灰色 */
.tool-row {
  width: 100%;
  font-size: 12px;
  color: var(--app-text-secondary);
  line-height: 20px;
}
.tool-row-head {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: var(--app-text-secondary);
}
.tool-arrow {
  color: var(--app-text-muted);
  display: flex;
  flex-shrink: 0;
}
.tool-summary {
  font-size: 12px;
  color: var(--app-text-secondary);
  word-break: break-all;
}
.tool-status {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
  color: var(--app-text-muted);
}
.tool-status.running {
  color: var(--app-primary);
}
.tool-status.awaiting {
  color: #f59e0b;
}
.tool-status.failed {
  color: #ef4444;
}
.tool-status.cancelled {
  color: var(--app-text-muted);
}
.tool-status.ok {
  color: #16a34a;
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
  border-radius: var(--app-radius-sm);
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
