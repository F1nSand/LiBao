<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useKbStore } from '@/stores/kb'
import type { KbDocument } from '@/types'

/** 文档上传（docs/02 §6.2）：拖拽/选择 → POST 上传（分块→向量化由后端异步，ChunkStatus 轮询） */
const props = defineProps<{ collectionId: string }>()
const emit = defineEmits<{ uploaded: [doc: KbDocument] }>()

const kb = useKbStore()
const uploading = ref(false)
const progress = ref(0)

async function doUpload(file: File) {
  if (!props.collectionId) {
    ElMessage.warning('请先选择集合')
    return
  }
  uploading.value = true
  progress.value = 0
  try {
    const doc = await kb.upload(props.collectionId, file, (p) => (progress.value = p))
    emit('uploaded', doc)
    ElMessage.success(`已上传：${file.name}，进入分块/索引流程`)
  } catch (e) {
    ElMessage.error('上传失败')
    console.error(e)
  } finally {
    uploading.value = false
  }
}

function onChange(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) void doUpload(file)
  ;(e.target as HTMLInputElement).value = ''
}

function onDrop(e: DragEvent) {
  const file = e.dataTransfer?.files?.[0]
  if (file) void doUpload(file)
}
</script>

<template>
  <div class="kb-upload">
    <input id="kb-file-input" type="file" hidden @change="onChange" />
    <label for="kb-file-input" class="kb-drop" @dragover.prevent @drop.prevent="onDrop">
      <el-icon :size="22"><UploadFilled /></el-icon>
      <span>拖拽文档到此处，或点击选择</span>
      <span v-if="uploading" class="kb-progress">上传中 {{ progress }}%</span>
    </label>
  </div>
</template>

<style scoped>
.kb-drop {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px dashed var(--app-border);
  border-radius: var(--app-radius);
  padding: 18px;
  cursor: pointer;
  color: var(--app-text-secondary);
  font-size: var(--app-font-size-sm);
  transition: border-color 0.2s;
}
.kb-drop:hover {
  border-color: var(--app-primary);
  color: var(--app-primary);
}
.kb-progress {
  color: var(--app-primary);
}
</style>
