<script setup lang="ts">
import type { InterruptInfo } from '@/composables/useChatStream'
import JsonViewer from '@/components/common/JsonViewer.vue'

/** 中断确认弹窗（docs/02 §5.3）：确认 → resume approved；拒绝 → resume denied */
defineProps<{ visible: boolean; info: InterruptInfo | null }>()
const emit = defineEmits<{ confirm: [approved: boolean] }>()
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="工具调用确认"
    width="480px"
    :close-on-click-modal="false"
    :show-close="false"
  >
    <div class="interrupt-body">
      <el-alert type="warning" :closable="false" show-icon>
        <template #title>
          Agent 请求执行工具操作，需你确认
        </template>
      </el-alert>
      <div v-if="info" class="interrupt-detail">
        <div class="interrupt-row">
          <span class="interrupt-label">节点</span>
          <span class="interrupt-value mono">{{ info.node_id }}</span>
        </div>
        <div v-if="info.payload !== undefined" class="interrupt-row">
          <span class="interrupt-label">载荷</span>
          <div class="interrupt-json"><JsonViewer :data="info.payload" /></div>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button @click="emit('confirm', false)">拒绝</el-button>
      <el-button type="primary" @click="emit('confirm', true)">确认执行</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.interrupt-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.interrupt-detail {
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius);
  padding: 10px;
}
.interrupt-row {
  display: flex;
  gap: 10px;
  margin-bottom: 6px;
}
.interrupt-label {
  color: var(--app-text-muted);
  font-size: 12px;
  flex-shrink: 0;
  width: 44px;
}
.interrupt-value {
  word-break: break-all;
}
.mono {
  font-family: var(--app-font-mono);
}
.interrupt-json {
  flex: 1;
  min-width: 0;
  max-height: 180px;
  overflow: auto;
  background: var(--app-bg);
  border-radius: var(--app-radius-sm);
  padding: 6px;
}
</style>
