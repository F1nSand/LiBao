<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AttachmentRef } from '@/types'
import { getAttachmentAnalysis } from '@/api/uploads'

/**
 * 附件消息渲染（docs/02 §5.3.2）：图片缩略图/文件卡 + 分析状态徽标。
 * failed 不阻塞对话；分析结果就绪后展示摘要。
 */
const props = defineProps<{ refs: AttachmentRef[] }>()

interface Item {
  attachment_id: string
  name: string
  mime_type: string
  status: string
  summary?: string
}

const items = ref<Item[]>([])

function isImage(mime: string | undefined): boolean {
  return !!mime?.startsWith('image/')
}

function sync() {
  items.value = props.refs.map((r) => ({
    attachment_id: r.attachment_id,
    name: r.name ?? `附件 ${r.attachment_id.slice(0, 8)}`,
    mime_type: r.mime_type ?? '',
    status: r.status ?? 'uploaded',
  }))
}

let timer: ReturnType<typeof setInterval> | null = null

async function checkAnalysis() {
  const pending = items.value.filter((it) => it.status === 'uploaded' || it.status === 'analyzing')
  if (pending.length === 0) {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
    return
  }
  for (const it of pending) {
    try {
      const res = await getAttachmentAnalysis(it.attachment_id)
      it.status = res.status
      it.summary = res.summary
    } catch {
      it.status = 'failed'
    }
  }
}

watch(() => props.refs, sync, { immediate: true, deep: true })

onMounted(() => {
  sync()
  if (items.value.some((it) => it.status === 'uploaded' || it.status === 'analyzing')) {
    timer = setInterval(() => void checkAnalysis(), 2500)
  }
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="attach-list">
    <div v-for="it in items" :key="it.attachment_id" class="attach-item">
      <div v-if="isImage(it.mime_type)" class="attach-img-wrap">
        <el-image :src="`/api/v1/attachments/${it.attachment_id}`" fit="cover" class="attach-img" :preview-src-list="[`/api/v1/attachments/${it.attachment_id}`]" />
      </div>
      <div v-else class="attach-file">
        <el-icon><Document /></el-icon>
        <span class="attach-name">{{ it.name }}</span>
      </div>
      <span class="attach-badge" :class="it.status">
        <el-icon v-if="it.status === 'analyzing' || it.status === 'uploaded'" class="is-loading"><Loading /></el-icon>
        {{ it.status === 'analyzing' ? '分析中' : it.status === 'uploaded' ? '待分析' : it.status === 'ready' ? '已分析' : it.status === 'failed' ? '分析失败' : '' }}
      </span>
      <div v-if="it.status === 'ready' && it.summary" class="attach-summary">{{ it.summary }}</div>
    </div>
  </div>
</template>

<style scoped>
.attach-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 6px;
}
.attach-item {
  position: relative;
  max-width: 240px;
}
.attach-img {
  width: 120px;
  height: 90px;
  border-radius: var(--app-radius);
  border: 1px solid var(--app-border);
}
.attach-file {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #fafbfc;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  padding: 6px 10px;
  font-size: 12px;
}
.attach-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 160px;
}
.attach-badge {
  position: absolute;
  top: 4px;
  right: 4px;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  color: #fff;
}
.attach-badge.uploaded,
.attach-badge.analyzing {
  background: rgba(99, 102, 241, 0.85);
}
.attach-badge.ready {
  background: rgba(34, 197, 94, 0.9);
}
.attach-badge.failed {
  background: rgba(239, 68, 68, 0.9);
}
.attach-summary {
  margin-top: 4px;
  font-size: 12px;
  color: var(--app-text-secondary);
}
</style>
