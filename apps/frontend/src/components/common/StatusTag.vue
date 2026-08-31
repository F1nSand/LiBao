<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

/** 状态 → Element Plus tag 类型/文案（/chat 状态栏与 /tasks 复用） */
const MAP: Record<string, { type: 'primary' | 'success' | 'warning' | 'danger' | 'info'; label: string }> = {
  idle: { type: 'info', label: '空闲' },
  running: { type: 'primary', label: '运行中' },
  thinking: { type: 'primary', label: '思考中' },
  waiting_confirm: { type: 'warning', label: '等待确认' },
  done: { type: 'success', label: '完成' },
  failed: { type: 'danger', label: '失败' },
  pending: { type: 'info', label: '排队中' },
  cancelled: { type: 'info', label: '已取消' },
  published: { type: 'success', label: '已发布' },
  draft: { type: 'info', label: '草稿' },
  disabled: { type: 'info', label: '已下线' },
  indexed: { type: 'success', label: '已索引' },
  chunking: { type: 'primary', label: '分块中' },
  indexing: { type: 'primary', label: '索引中' },
  uploaded: { type: 'info', label: '已上传' },
  analyzing: { type: 'primary', label: '分析中' },
  ready: { type: 'success', label: '就绪' },
}

const cfg = computed(() => MAP[props.status] ?? { type: 'info', label: props.status })
</script>

<template>
  <!-- 空/未知状态不渲染气泡（如流式初始 status=null，避免出现空的 tag） -->
  <el-tag v-if="cfg.label" :type="cfg.type" size="small" disable-transitions>{{ cfg.label }}</el-tag>
</template>
