<script setup lang="ts">
import { ref, watch } from 'vue'
import type { AttachmentRef } from '@/types'

/**
 * 附件消息渲染（《02》前端设计 §5.3.2）：图片缩略图/文件卡。
 * 上传/解析是后端内部流程，不在附件气泡上展示状态或启动轮询。
 */
const props = defineProps<{ refs: AttachmentRef[] }>()

interface Item {
  attachment_id: string
  name: string
  mime_type: string
  size?: number
}

const items = ref<Item[]>([])

function isImage(mime: string | undefined): boolean {
  return !!mime?.startsWith('image/')
}

function attachmentUrl(id: string): string {
  return `/api/v1/attachments/${encodeURIComponent(id)}`
}

function extension(name: string): string {
  const value = name.split('.').pop()?.toUpperCase() ?? ''
  return value.length <= 5 ? value : 'FILE'
}

function sync() {
  items.value = props.refs.map((r) => ({
    attachment_id: r.attachment_id,
    name: r.name ?? `附件 ${r.attachment_id.slice(0, 8)}`,
    mime_type: r.mime_type ?? '',
    size: r.size,
  }))
}

watch(() => props.refs, sync, { immediate: true, deep: true })

function formatSize(size?: number): string {
  if (size === undefined || size < 0) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${Math.round(size / 102.4) / 10} KB`
  return `${Math.round(size / (1024 * 102.4)) / 10} MB`
}
</script>

<template>
  <div class="attach-list">
    <div v-for="it in items" :key="it.attachment_id" class="attach-item">
      <div v-if="isImage(it.mime_type)" class="attach-img-wrap">
        <el-image :src="attachmentUrl(it.attachment_id)" fit="cover" class="attach-img" :preview-src-list="[attachmentUrl(it.attachment_id)]" />
        <span class="attach-img-caption" :title="it.name">{{ it.name }}</span>
      </div>
      <a
        v-else
        class="attach-file"
        :href="attachmentUrl(it.attachment_id)"
        target="_blank"
        rel="noopener noreferrer"
        :download="it.name"
        :aria-label="`打开附件 ${it.name}`"
      >
        <span class="attach-file-icon" aria-hidden="true"><el-icon :size="22"><Document /></el-icon></span>
        <span class="attach-file-info">
          <span class="attach-name">{{ it.name }}</span>
          <span class="attach-meta">
            <span class="attach-type">{{ extension(it.name) }}</span>
            <span v-if="formatSize(it.size)" class="attach-size">{{ formatSize(it.size) }}</span>
          </span>
        </span>
        <el-icon class="attach-download" :size="18" aria-hidden="true"><Download /></el-icon>
      </a>
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
  max-width: min(360px, 100%);
}
.attach-img-wrap {
  position: relative;
  width: 220px;
}
.attach-img {
  display: block;
  width: 220px;
  height: 150px;
  border-radius: var(--app-radius-lg);
  border: 1px solid var(--app-border);
  background: var(--app-bg);
}
.attach-img-caption {
  display: block;
  max-width: 100%;
  margin-top: 5px;
  overflow: hidden;
  color: var(--app-text-secondary);
  font-size: var(--app-font-size-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.attach-file {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 250px;
  max-width: min(360px, calc(100vw - 120px));
  min-height: 72px;
  box-sizing: border-box;
  background: linear-gradient(135deg, var(--app-content-bg), color-mix(in srgb, var(--app-primary) 5%, var(--app-content-bg)));
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  padding: 12px 14px;
  color: var(--app-text-main);
  font-size: var(--app-font-size-sm);
  text-decoration: none;
  transition: border-color 0.15s var(--ease-out), background 0.15s var(--ease-out), transform 0.15s var(--ease-out);
}
.attach-file:hover,
.attach-file:focus-visible {
  border-color: var(--app-primary);
  background: color-mix(in srgb, var(--app-primary) 9%, var(--app-content-bg));
  outline: none;
  transform: translateY(-1px);
}
.attach-file:focus-visible {
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-primary) 22%, transparent);
}
.attach-file-icon {
  display: grid;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  place-items: center;
  border-radius: var(--app-radius);
  background: color-mix(in srgb, var(--app-primary) 13%, transparent);
  color: var(--app-primary);
}
.attach-file-info {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.attach-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}
.attach-meta {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--app-text-muted);
  font-size: var(--app-font-size-xs);
}
.attach-type {
  color: var(--app-link);
  font-weight: 600;
}
.attach-size {
  color: var(--app-text-muted);
}
.attach-download {
  flex: 0 0 auto;
  color: var(--app-text-muted);
}
@media (max-width: 480px) {
  .attach-file {
    min-width: min(250px, calc(100vw - 104px));
    max-width: calc(100vw - 104px);
  }
  .attach-img-wrap,
  .attach-img {
    width: min(220px, calc(100vw - 104px));
  }
}
</style>
