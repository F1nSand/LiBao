<script setup lang="ts">
import { computed, ref } from 'vue'
import { useKbStore } from '@/stores/kb'
import { useTaskPoll } from '@/composables/useTaskPoll'
import type { KbDocument } from '@/types'

/** 分块/索引进度（docs/02 §6.2 / docs/03 §5.6）：状态轮询，终态即停 */
const props = defineProps<{ document: KbDocument }>()

const kb = useKbStore()

function isProcessing(s: string | undefined): boolean {
  return s === 'chunking' || s === 'indexing'
}

// 用独立 liveStatus 驱动轮询启停（避免 data 自引用）；终态（indexed/failed/archived）即停
const liveStatus = ref<string | undefined>(props.document.status)
const processing = computed(() => isProcessing(liveStatus.value ?? props.document.status))

const { data } = useTaskPoll(
  async () => {
    const d = await kb.status(props.document.id)
    liveStatus.value = d.status
    return d
  },
  { intervalMs: 3000, enabled: processing },
)

const progress = computed(() => data.value?.progress ?? props.document.progress ?? 0)
const status = computed(() => liveStatus.value ?? props.document.status)
const chunkCount = computed(() => data.value?.chunk_count ?? props.document.chunk_count)

const STATUS_LABEL: Record<string, string> = {
  uploaded: '已上传',
  chunking: '分块中',
  indexing: '索引中',
  indexed: '已索引',
  failed: '失败',
  archived: '已归档',
}
</script>

<template>
  <div class="chunk-status">
    <div class="chunk-row">
      <el-tag
        size="small"
        :type="status === 'indexed' ? 'success' : status === 'failed' ? 'danger' : 'primary'"
        disable-transitions
      >
        {{ STATUS_LABEL[status] ?? status }}
      </el-tag>
      <span v-if="chunkCount != null" class="chunk-count">{{ chunkCount }} chunks</span>
    </div>
    <el-progress
      v-if="processing"
      :percentage="progress"
      :stroke-width="6"
      :status="progress >= 100 ? 'success' : undefined"
    />
    <div v-if="status === 'failed'" class="chunk-error">{{ props.document.error ?? '索引失败' }}</div>
  </div>
</template>

<style scoped>
.chunk-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chunk-count {
  font-size: 12px;
  color: var(--app-text-muted);
}
.chunk-error {
  color: #ef4444;
  font-size: 12px;
}
</style>
