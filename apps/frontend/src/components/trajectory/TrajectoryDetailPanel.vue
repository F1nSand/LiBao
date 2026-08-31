<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { TrajectoryCell } from '@/utils/trajectory'
import { kindLabel } from '@/utils/trajectory'
import { lineDiff } from '@/utils/diff'
import { formatDate, formatDuration, formatTime } from '@/utils/format'
import JsonViewer from '@/components/common/JsonViewer.vue'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'

/** 详情面板（《02》前端设计 §6.3）：按 kind 切标签页；JsonViewer / MarkdownRenderer 复用 */
const props = defineProps<{ cell: TrajectoryCell | null }>()
const emit = defineEmits<{ close: [] }>()

const activeTab = ref('preview')
watch(
  () => props.cell,
  () => {
    activeTab.value = props.cell?.kind === 'tool' ? 'payload' : 'preview'
  },
)

const isTool = computed(() => props.cell?.kind === 'tool')
const tokenTotal = computed(() => props.cell?.tokenUsage?.total_tokens)
const diffSegments = computed(() =>
  props.cell?.diff ? lineDiff(props.cell.diff.before, props.cell.diff.after) : [],
)
</script>

<template>
  <div class="tj-detail">
    <template v-if="cell">
      <div class="tj-detail-head">
        <span class="tj-detail-title mono">#{{ cell.index }} · {{ kindLabel(cell.kind) }}</span>
        <span class="tj-detail-summary">{{ cell.text }}</span>
        <button class="tj-close" type="button" title="关闭详情" aria-label="关闭详情" @click="emit('close')">✕</button>
      </div>

      <el-tabs v-model="activeTab" size="small" class="tj-tabs">
        <!-- 非工具：预览 / 原文（user/steering/context/message/compacted） -->
        <template v-if="!isTool">
          <el-tab-pane label="预览" name="preview">
            <MarkdownRenderer v-if="cell.previewMarkdown" :raw="cell.previewMarkdown" />
            <div v-else class="tj-placeholder">No content captured</div>
          </el-tab-pane>
          <el-tab-pane label="原文" name="raw">
            <pre v-if="cell.content" class="tj-pre">{{ cell.content }}</pre>
            <div v-else class="tj-placeholder">No content captured</div>
          </el-tab-pane>
          <!-- 用量：仅 message -->
          <el-tab-pane v-if="cell.kind === 'message'" label="用量" name="usage">
            <div v-if="cell.tokenUsage" class="tj-metrics">
              <div class="tj-metric"><span class="tj-metric-label">开始时间</span><span class="tj-metric-value">{{ formatDate(new Date(cell.startedAt).toISOString()) }}</span></div>
              <div class="tj-metric"><span class="tj-metric-label">耗时</span><span class="tj-metric-value mono">{{ formatDuration(cell.durationMs) }}</span></div>
              <div class="tj-metric"><span class="tj-metric-label">Tokens</span><span class="tj-metric-value mono">{{ tokenTotal != null ? tokenTotal : 'Usage not reported' }}</span></div>
              <JsonViewer :data="cell.tokenUsage" />
            </div>
            <div v-else class="tj-placeholder">Usage not reported</div>
          </el-tab-pane>
          <!-- 思考：仅 message 且有 thinking -->
          <el-tab-pane v-if="cell.kind === 'message' && cell.thinking" label="思考" name="thinking">
            <pre class="tj-pre tj-think">{{ cell.thinking }}</pre>
          </el-tab-pane>
          <!-- Diff：仅 context 且有 diff -->
          <el-tab-pane v-if="cell.kind === 'context' && cell.diff" label="Diff" name="diff">
            <div class="tj-diff">
              <div v-for="(seg, i) in diffSegments" :key="i" class="tj-diff-seg" :class="`tj-diff-${seg.type}`">
                <div v-for="line in seg.lines" :key="line" class="tj-diff-line">
                  <span class="tj-diff-mark mono">{{ seg.type === 'add' ? '+' : seg.type === 'del' ? '-' : ' ' }}</span>
                  <span class="tj-diff-code">{{ line }}</span>
                </div>
              </div>
            </div>
          </el-tab-pane>
        </template>

        <!-- 工具：入参 / 结果 / 时序（Schema 数据不携带，不设占位 tab） -->
        <template v-else>
          <el-tab-pane label="入参" name="payload">
            <JsonViewer v-if="cell.input !== undefined" :data="cell.input" />
            <div v-else class="tj-placeholder">No payload captured</div>
          </el-tab-pane>
          <el-tab-pane label="结果" name="result">
            <JsonViewer v-if="cell.output !== undefined" :data="cell.output" />
            <div v-else class="tj-placeholder">No result captured</div>
          </el-tab-pane>
          <el-tab-pane label="时序" name="timing">
            <div class="tj-metrics">
              <div class="tj-metric"><span class="tj-metric-label">状态</span><span class="tj-metric-value" :class="{ err: cell.isError }">{{ cell.isError ? 'Failed' : 'Completed' }}</span></div>
              <div class="tj-metric"><span class="tj-metric-label">开始时间</span><span class="tj-metric-value">{{ formatTime(cell.startedAt) }}</span></div>
              <div class="tj-metric"><span class="tj-metric-label">耗时</span><span class="tj-metric-value mono">{{ formatDuration(cell.durationMs) }}</span></div>
              <div class="tj-metric"><span class="tj-metric-label">工具</span><span class="tj-metric-value mono">{{ cell.toolName ?? '—' }}</span></div>
            </div>
          </el-tab-pane>
        </template>
      </el-tabs>
    </template>
    <div v-else class="tj-detail-empty">选择一条记录查看详情</div>
  </div>
</template>

<style scoped>
.tj-detail {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  background: var(--app-content-bg);
  overflow: hidden;
  min-width: 0;
  box-shadow: var(--app-shadow-card);
}
.tj-detail-head {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: var(--app-bg);
  border-bottom: 1px solid var(--app-border-light);
}
.tj-detail-title {
  font-weight: 600;
  color: var(--app-text-main);
  white-space: nowrap;
}
.tj-detail-summary {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-text-secondary);
  font-size: var(--app-font-size-xs);
}
.tj-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  min-height: 32px;
  border: none;
  background: none;
  cursor: pointer;
  color: var(--app-text-muted);
  font-size: 14px;
  padding: 2px;
}
.tj-close:hover {
  color: var(--app-text-main);
}
.tj-tabs {
  padding: 0 10px 10px;
}
.tj-pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--app-font-mono);
  font-size: var(--app-font-size-xs);
  line-height: 1.6;
  color: var(--app-text-main);
}
.tj-placeholder {
  color: var(--app-text-muted);
  font-size: var(--app-font-size-xs);
  padding: 12px 0;
}
.tj-diff {
  font-family: var(--app-font-mono);
  font-size: var(--app-font-size-xs);
  line-height: 1.6;
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius-sm);
  overflow: auto;
}
.tj-diff-line {
  display: flex;
  gap: 8px;
  padding: 0 8px;
}
.tj-diff-add .tj-diff-line {
  background: #ecfdf3;
}
.tj-diff-del .tj-diff-line {
  background: #fef2f2;
}
.tj-diff-mark {
  width: 14px;
  flex-shrink: 0;
  color: var(--app-text-muted);
  user-select: none;
}
.tj-diff-add .tj-diff-mark {
  color: var(--app-success);
}
.tj-diff-del .tj-diff-mark {
  color: var(--app-danger);
}
.tj-diff-code {
  white-space: pre-wrap;
  word-break: break-word;
}
.tj-think {
  color: var(--app-text-secondary);
  border-left: 3px solid var(--el-color-primary-light-5);
  padding-left: 8px;
}
.tj-metrics {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tj-metric {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--app-font-size-xs);
}
.tj-metric-label {
  width: 64px;
  color: var(--app-text-muted);
  flex-shrink: 0;
}
.tj-metric-value {
  color: var(--app-text-main);
}
.tj-metric-value.err {
  color: var(--app-danger);
}
.tj-detail-empty {
  padding: 30px 20px;
  text-align: center;
  color: var(--app-text-muted);
  font-size: 13px;
}
.mono {
  font-family: var(--app-font-mono);
}
</style>
