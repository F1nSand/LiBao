<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import ResponsiveDialog from '@/components/common/ResponsiveDialog.vue'
import { createRestorePreview, executeRestore } from '@/api/checkpoints'
import type { RestorePreview, RestoreResult, RollbackMode } from '@/types'

const props = defineProps<{
  modelValue: boolean
  conversationId: string
  checkpointId: string
  messageId: string
}>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; completed: [result: RestoreResult] }>()

const mode = ref<RollbackMode>('both')
const preview = ref<RestorePreview | null>(null)
const loading = ref(false)
const executing = ref(false)
const error = ref('')
const modeOptions = [
  { value: 'both' as const, label: '代码和对话', description: '恢复文件，并清空本条消息之后的对话' },
  { value: 'code_only' as const, label: '仅代码', description: '只恢复工作区文件，完整保留对话历史' },
  { value: 'conversation_only' as const, label: '仅对话', description: '截断到本条消息，文件保持现状' },
]

const fileChanges = computed(() => preview.value?.files ?? [])
const hasConflicts = computed(() => fileChanges.value.some((item) => item.conflict))

async function loadPreview() {
  if (!props.modelValue || !props.conversationId || !props.checkpointId) return
  loading.value = true
  error.value = ''
  try {
    preview.value = await createRestorePreview(props.conversationId, {
      target_checkpoint_id: props.checkpointId,
      mode: mode.value,
    })
  } catch (e) {
    preview.value = null
    error.value = e instanceof Error ? e.message : '无法生成回滚预览'
  } finally {
    loading.value = false
  }
}

watch(() => props.modelValue, (visible) => {
  if (visible) void loadPreview()
})
watch(mode, () => {
  if (props.modelValue) void loadPreview()
})

async function confirmRestore() {
  if (!preview.value || executing.value) return
  executing.value = true
  try {
    const result = await executeRestore(props.conversationId, preview.value.preview_id)
    ElMessage.success(result.status === 'partial' ? '已回滚可安全恢复的文件，冲突文件已跳过' : '已完成回滚')
    emit('completed', result)
    emit('update:modelValue', false)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '回滚失败，请重新预览')
  } finally {
    executing.value = false
  }
}
</script>

<template>
  <ResponsiveDialog
    :model-value="modelValue"
    title="回滚到此状态"
    width="760px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="restore-dialog">
      <p class="restore-lede">先选择回滚范围，确认后才会修改工作区或对话。</p>
      <div class="mode-grid" role="radiogroup" aria-label="回滚模式">
        <label v-for="option in modeOptions" :key="option.value" class="mode-option" :class="{ selected: mode === option.value }">
          <input v-model="mode" type="radio" name="restore-mode" :value="option.value" />
          <span class="mode-copy"><b>{{ option.label }}</b><small>{{ option.description }}</small></span>
        </label>
      </div>

      <div v-loading="loading" class="preview-panel">
        <div v-if="error" class="restore-error" role="alert">{{ error }}</div>
        <template v-else-if="preview">
          <div class="preview-meta">
            <span>{{ fileChanges.length }} 个文件变更</span>
            <span v-if="preview.conversation.hidden_message_count">将隐藏 {{ preview.conversation.hidden_message_count }} 条消息</span>
          </div>
          <div v-if="!fileChanges.length && mode !== 'conversation_only'" class="preview-empty">此节点没有可恢复的文件变更。</div>
          <div v-for="file in fileChanges" :key="file.path" class="file-preview" :class="{ conflict: file.conflict }">
            <div class="file-heading">
              <span class="file-path">{{ file.path }}</span>
              <span class="file-action">{{ file.conflict ? '跳过冲突' : file.action === 'delete' ? '删除' : '恢复' }}</span>
            </div>
            <p v-if="file.reason" class="file-reason">{{ file.reason }}</p>
            <pre v-if="file.diff" class="file-diff">{{ file.diff }}<span v-if="file.diff_truncated">…（diff 已截断）</span></pre>
            <p v-else class="binary-note">{{ file.content_kind === 'binary' ? '二进制文件：将按完整 bytes 恢复' : '无文本 diff' }}</p>
          </div>
          <div class="restore-warnings">
            <p v-for="warning in preview.warnings" :key="warning">{{ warning }}</p>
          </div>
          <p v-if="hasConflicts" class="conflict-note">冲突文件会被安全跳过，其余文件仍可继续恢复。</p>
        </template>
      </div>
    </div>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="executing" :disabled="!preview || loading" @click="confirmRestore">确认回滚</el-button>
    </template>
  </ResponsiveDialog>
</template>

<style scoped>
.restore-dialog { color: var(--app-text-primary); }
.restore-lede { margin: 0 0 14px; color: var(--app-text-secondary); font-size: 13px; }
.mode-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.mode-option { display: flex; gap: 8px; min-height: 76px; padding: 11px; border: 1px solid var(--app-border-light); border-radius: 9px; cursor: pointer; }
.mode-option.selected { border-color: var(--app-primary); background: color-mix(in srgb, var(--app-primary) 7%, transparent); }
.mode-option input { accent-color: var(--app-primary); margin-top: 3px; }
.mode-copy { display: grid; gap: 5px; }
.mode-copy small { color: var(--app-text-muted); line-height: 1.45; }
.preview-panel { min-height: 160px; margin-top: 16px; padding: 12px; border: 1px solid var(--app-border-light); border-radius: 9px; background: var(--app-bg); }
.preview-meta { display: flex; justify-content: space-between; margin-bottom: 10px; color: var(--app-text-secondary); font-size: 12px; }
.preview-empty, .binary-note { color: var(--app-text-muted); font-size: 12px; }
.file-preview { margin: 8px 0; overflow: hidden; border: 1px solid var(--app-border-light); border-radius: 7px; background: var(--app-content-bg); }
.file-preview.conflict { border-color: color-mix(in srgb, #d97706 50%, var(--app-border)); }
.file-heading { display: flex; justify-content: space-between; gap: 8px; padding: 7px 9px; font-size: 12px; }
.file-path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--app-font-mono); }
.file-action { color: var(--app-link); white-space: nowrap; }
.conflict .file-action { color: #b45309; }
.file-reason { margin: 0; padding: 0 9px 6px; color: #b45309; font-size: 12px; }
.file-diff { max-height: 180px; margin: 0; overflow: auto; padding: 8px 9px; border-top: 1px solid var(--app-border-light); background: color-mix(in srgb, var(--app-bg) 80%, #0f172a 20%); color: #dbeafe; font: 11px/1.5 var(--app-font-mono); white-space: pre-wrap; }
.restore-warnings { margin-top: 12px; color: var(--app-text-muted); font-size: 11px; line-height: 1.5; }
.restore-warnings p { margin: 2px 0; }
.conflict-note { margin: 10px 0 0; color: #b45309; font-size: 12px; }
.restore-error { color: var(--app-danger, #dc2626); font-size: 13px; }
@media (max-width: 680px) { .mode-grid { grid-template-columns: 1fr; } .mode-option { min-height: 0; } }
</style>
