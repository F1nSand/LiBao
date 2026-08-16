<script setup lang="ts">
import { computed } from 'vue'

/** 工具调用卡（docs/02 §6.2）：只显示工具名 + 调用状态；原始参数（输入/输出/耗时）不展示。
 * 失败仅保留错误文案——重试由 agent/用户以语言发起，不由前端点击重试决定。 */
const props = defineProps<{
  toolName: string
  status?: string
  error?: string
}>()

const isRunning = computed(() => props.status === 'running' || props.status === 'pending')
const isFailed = computed(() => props.status === 'error' || props.status === 'timeout' || props.status === 'failed')
const isCancelled = computed(() => props.status === 'cancelled')
const isAwaiting = computed(() => props.status === 'awaiting_confirm')
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
    </div>

    <div v-if="error || isFailed" class="tool-body">
      <div v-if="error" class="tool-error">{{ error }}</div>
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
.tool-body {
  max-width: 100%;
}
.tool-error {
  color: #ef4444;
  font-size: 12px;
  overflow-wrap: anywhere;
}
</style>
