<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { uploadAttachment } from '@/api/uploads'
import { ApiError } from '@/api/http'
import { UPLOAD_MAX_BYTES } from '@/types'

/**
 * 消息输入区附件上传（docs/02 §6.2 H1 / docs/03 §5.9）：
 * 选择/拖拽 → POST /uploads → emit attachment_id；40011/40012 即时提示；失败重试（幂等）。
 */
const emit = defineEmits<{ add: [attachmentId: string] }>()

const uploading = ref(false)
const progress = ref(0)

const ACCEPT = 'image/*,.pdf,.doc,.docx,.txt,.md'

async function doUpload(file: File) {
  if (file.size > UPLOAD_MAX_BYTES) {
    ElMessage.error(`文件超过 20MB 上限（${file.name}）`)
    return
  }
  uploading.value = true
  progress.value = 0
  try {
    const res = await uploadAttachment(file, (p) => (progress.value = p))
    emit('add', res.attachment_id)
    ElMessage.success(`已上传：${file.name}`)
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.code === 40011) ElMessage.error('文件超限')
      else if (e.code === 40012) ElMessage.error('文件类型不支持')
      else ElMessage.error(`上传失败：${e.message}`)
    } else {
      ElMessage.error('上传失败，请重试')
    }
  } finally {
    uploading.value = false
  }
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) void doUpload(file)
  input.value = ''
}

function onDrop(e: DragEvent) {
  const file = e.dataTransfer?.files?.[0]
  if (file) void doUpload(file)
}
</script>

<template>
  <div class="uploader">
    <input id="file-input" type="file" :accept="ACCEPT" hidden @change="onFileChange" />
    <label
      class="upload-btn"
      for="file-input"
      title="上传附件（≤20MB）"
      @dragover.prevent
      @drop.prevent="onDrop"
    >
      <el-icon :size="18"><Paperclip /></el-icon>
      <span v-if="uploading" class="upload-progress">{{ progress }}%</span>
    </label>
  </div>
</template>

<style scoped>
.upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px;
  border-radius: var(--app-radius);
  cursor: pointer;
  color: var(--app-text-secondary);
}
.upload-btn:hover {
  background: var(--app-bg);
  color: var(--app-primary);
}
.upload-progress {
  font-size: 11px;
  color: var(--app-primary);
}
</style>
