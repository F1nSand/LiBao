<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '@/stores/chat'
import { useChatStream } from '@/composables/useChatStream'
import { TOKEN_LIMIT } from '@/types'
import type { AttachmentRef, ComposerAttachment, Message, RestoreResult } from '@/types'
import type { RestoreDialogTarget } from '@/api/checkpoints'
import { truncate } from '@/utils/format'
import MessageList from '@/components/business/MessageList.vue'
import TrajectoryPanel from '@/components/trajectory/TrajectoryPanel.vue'
import AttachmentUploader, { type PendingAttachment } from '@/components/business/AttachmentUploader.vue'
import InterruptConfirmDialog from '@/components/business/InterruptConfirmDialog.vue'
import AgentRunStatus from '@/components/common/AgentRunStatus.vue'
import CheckpointRestoreDialog from '@/components/business/CheckpointRestoreDialog.vue'
import ModelPicker from '@/components/business/ModelPicker.vue'
import RollbackUndoBanner from '@/components/business/RollbackUndoBanner.vue'
import { composerFingerprint } from '@/utils/checkpointRestore'

/** 对话工作台（《02》前端设计 §4 / §5）：消息流 + 流式渲染 + 工具卡 + 中断确认 + 会话|轨迹切换（单通用 Agent，无切换） */
const chat = useChatStore()
const stream = useChatStream({
  onCheckpointAnchor: chat.reconcileCheckpointAnchor,
  onPersistedMessage: (message) => {
    // 多流：后台流（其它会话）封口的消息不得 append 进当前会话列表（回该会话时服务端 loadMessages 补齐）
    const m0 = (message ?? {}) as Partial<Message>
    if (m0.conversation_id && m0.conversation_id !== chat.currentId) return
    // 用流式状态兜底补齐 done 消息：真实后端 done 的 message 可能缺 content（内容未就绪），
    // 直接 append 会让完成瞬间文本气泡消失。这里补 content，且不再 refreshMessages
    // （刷新按 page1 分页会截断长会话的最新消息）。服务端一致性在重进会话/刷新页面时同步。
    const m = m0
    const hasContent = !!(m.content ?? '').trim()
    chat.appendAssistantMessage({
      id: m.id ?? stream.state.value.messageId ?? `local_asst_${Date.now()}`,
      conversation_id: m.conversation_id ?? chat.currentId ?? '',
      role: 'assistant',
      content: hasContent ? m.content! : stream.state.value.partialText,
      tool_calls: m.tool_calls?.length ? m.tool_calls : undefined,
      thinking: m.thinking,
      token_usage: m.token_usage,
      cost: m.cost,
      created_at: m.created_at ?? new Date().toISOString(),
    })
  },
  onTaskSettled: ({ conversationId, status }) => {
    // 长任务断线恢复收敛 done → reload 会话消息/轨迹（仅对应当前会话；背景会话切回时 loadMessages 自会补齐）
    if (conversationId && conversationId !== chat.currentId) return
    if (status === 'done') void chat.loadMessages(chat.currentId ?? '')
  },
})

/** 当前查看会话的流式状态（computed；切换会话时 useChatStream.setConversation 指向对应 entry） */
const currentStream = stream.state

const input = ref('')
const pendingAttachments = ref<ComposerAttachment[]>([])
const attachmentUploader = ref<InstanceType<typeof AttachmentUploader> | null>(null)
const isDragging = ref(false)
const lastFailedDraft = ref<{ content: string; attachments: ComposerAttachment[] } | null>(null)
const interruptVisible = ref(false)
const restoreVisible = ref(false)
const restoreTarget = ref<RestoreDialogTarget | null>(null)
const rollbackUndo = ref<{ operationId: string; fingerprint: string } | null>(null)

/** 会话 | 轨迹 视图切换 */
const mode = ref<'chat' | 'trajectory'>('chat')

// 切换会话：流式状态按会话隔离（setConversation 指向该会话 entry，不 reset 后台流；清输入/附件）
watch(
  () => chat.currentId,
  (id) => {
    if (id) stream.setConversation(id)
    restoreVisible.value = false
    restoreTarget.value = null
    rollbackUndo.value = null
    resetForNext()
  },
)

/** 流式中 / 中断等待中禁用输入框（done/error/stop 后自动恢复；按会话隔离——仅当前会话有流才禁） */
const composerDisabled = computed(() => currentStream.value.streaming || !!currentStream.value.interrupted)

function resetForNext() {
  input.value = ''
  pendingAttachments.value = []
  lastFailedDraft.value = null
}

const hasUnavailableAttachments = computed(() => pendingAttachments.value.some((attachment) => attachment.available === false))

async function send() {
  const content = input.value.trim()
  const attachments = [...pendingAttachments.value]
  if (hasUnavailableAttachments.value) {
    ElMessage.warning('请先移除不可用附件')
    return
  }
  if ((!content && !attachments.length) || composerDisabled.value) return
  input.value = ''
  pendingAttachments.value = []
  await sendWith(content, attachments)
}

async function stop() {
  try {
    const result = await stream.stop()
    if (result === 'unavailable') {
      ElMessage.warning('已停止当前页面流；后端未提供可取消任务')
    }
    if (!currentStream.value.streaming) resetForNext()
    return result
  } catch (e) {
    ElMessage.error(e instanceof Error ? `中断失败：${e.message}` : '中断失败，请重试')
    return undefined
  }
}

/** send() 的内容注入版 */
async function sendWith(content: string, attachmentRefs: ComposerAttachment[] = [], appendUser = true) {
  const attachments = attachmentRefs.map((attachment) => attachment.attachment_id)
  if (attachmentRefs.some((attachment) => attachment.available === false)) {
    ElMessage.warning('请先移除不可用附件')
    return
  }
  if ((!content && !attachments.length) || composerDisabled.value) return
  if (content.length > TOKEN_LIMIT) {
    ElMessage.error(`输入超过 ${TOKEN_LIMIT} 字符上限`)
    return
  }
  lastFailedDraft.value = null
  try {
    // 若当前会话不存在则新建
    if (!chat.currentId) {
      await chat.createConversation(truncate(content || '附件消息', 20))
    } else {
      // 标题兜底：新建按钮创建的「新会话」——后端首条消息落库时已改名，本地列表同步
      // （与后端 truncate 同语义，避免一直显示「新会话」）
      const cur = chat.conversations.find((c) => c.id === chat.currentId)
      if (cur && cur.title === '新会话') cur.title = truncate(content || '附件消息', 20)
    }
    if (appendUser) {
      const refs: AttachmentRef[] = attachmentRefs.map(({ available: _available, unavailable_reason: _reason, ...attachment }) => ({ ...attachment }))
      chat.appendUserMessage(content, refs)
    }
    const req = {
      conversation_id: chat.currentId,
      message: { content, role: 'user' as const, attachments: [...attachments] },
      stream: true as const,
    }
    await stream.start(req)
    if (currentStream.value.error) lastFailedDraft.value = { content, attachments: attachmentRefs }
  } catch (e) {
    lastFailedDraft.value = { content, attachments: attachmentRefs }
    ElMessage.error(e instanceof Error ? `发送失败：${e.message}` : '发送失败，请重试')
  }
}

function onAttach(attachment: PendingAttachment) {
  if (pendingAttachments.value.length >= 10) {
    ElMessage.warning('每条消息最多 10 个附件')
    return
  }
  pendingAttachments.value.push({ ...attachment, available: true, unavailable_reason: null })
}

function removeAttachment(id: string) {
  pendingAttachments.value = pendingAttachments.value.filter((attachment) => attachment.attachment_id !== id)
}

async function uploadFiles(files: File[]) {
  if (!attachmentUploader.value || composerDisabled.value) return
  for (const file of files) {
    if (pendingAttachments.value.length >= 10) {
      ElMessage.warning('每条消息最多 10 个附件')
      break
    }
    await attachmentUploader.value.upload(file)
  }
}

function onComposerDragOver() {
  if (!composerDisabled.value) isDragging.value = true
}

function onComposerDragLeave() {
  isDragging.value = false
}

function onComposerDrop(e: DragEvent) {
  isDragging.value = false
  const files = Array.from(e.dataTransfer?.files ?? [])
  void uploadFiles(files)
}

function onPaste(e: ClipboardEvent) {
  const files = Array.from(e.clipboardData?.files ?? []).filter((file) => file.type.startsWith('image/'))
  if (!files.length) return
  e.preventDefault()
  void uploadFiles(files)
}

function restoreDraft() {
  const draft = lastFailedDraft.value
  if (!draft) return
  input.value = draft.content
  pendingAttachments.value = draft.attachments.map((attachment) => ({ ...attachment }))
  lastFailedDraft.value = null
}

async function retryFailed() {
  const draft = lastFailedDraft.value
  if (!draft || composerDisabled.value) return
  await sendWith(draft.content, draft.attachments, false)
}

async function onRollback(message: Message) {
  // Claude Code semantics: never rewind while a tool can still mutate files.
  if (composerDisabled.value) {
    const stopResult = await stop()
    if (stopResult === 'already-finished' && chat.currentId && !await stream.reconcileTaskTerminal(chat.currentId)) {
      ElMessage.warning('当前任务尚未进入终态，请稍后再试')
      return
    }
    if (composerDisabled.value) {
      ElMessage.warning('当前任务尚未停止，请稍后再试')
      return
    }
  }
  const checkpointId = message.checkpoint_id ?? message.checkpoint?.id
  if (!checkpointId || !chat.currentId) return
  rollbackUndo.value = null
  restoreTarget.value = { type: 'checkpoint', checkpointId, messageId: message.id }
  restoreVisible.value = true
}

function onUndoRollback() {
  const operationId = rollbackUndo.value?.operationId
  if (!operationId || !chat.currentId) return
  restoreTarget.value = { type: 'rollback_operation_before', operationId }
  restoreVisible.value = true
}

async function onRestoreCompleted(result: RestoreResult) {
  const id = chat.currentId
  if (!id) return
  const target = restoreTarget.value
  restoreVisible.value = false
  restoreTarget.value = null
  if (result.conversation.action === 'withdraw_from_target') {
    stream.resetConversation(id)
    const draft = chat.applyConversationRestore(id, result.conversation)
    if (draft) {
      input.value = draft.content
      pendingAttachments.value = draft.attachments
      rollbackUndo.value = result.undo_available
        ? { operationId: result.operation_id, fingerprint: composerFingerprint(input.value, pendingAttachments.value, []) }
        : null
    }
  } else if (result.conversation.action === 'restore_cursor') {
    stream.resetConversation(id)
    const baseline = rollbackUndo.value
    const currentFingerprint = composerFingerprint(input.value, pendingAttachments.value, [])
    if (target?.type === 'rollback_operation_before' && baseline?.operationId === target.operationId) {
      if (baseline.fingerprint === currentFingerprint) resetForNext()
      else ElMessage.warning('未覆盖已编辑草稿')
    }
    rollbackUndo.value = result.undo_available
      ? { operationId: result.operation_id, fingerprint: composerFingerprint(input.value, pendingAttachments.value, []) }
      : null
  }
  if (target?.type === 'checkpoint' && result.undo_available && !rollbackUndo.value) {
    rollbackUndo.value = { operationId: result.operation_id, fingerprint: composerFingerprint(input.value, pendingAttachments.value, []) }
  }
  if (result.conversation.action !== 'unchanged') await chat.loadMessages(id)
  await chat.loadConversations()
}

// 中断 → 弹窗
watch(
  () => stream.state.value.interrupted,
  (v) => (interruptVisible.value = !!v),
)

async function onInterruptConfirm(approved: boolean) {
  await stream.confirmInterrupt(approved)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void send()
  }
}

</script>

<template>
  <div class="chat-view">
    <div class="chat-main">
      <div class="chat-toolbar">
        <el-radio-group v-model="mode" size="small">
          <el-radio-button value="chat">会话</el-radio-button>
          <el-radio-button value="trajectory" :disabled="!chat.currentId">轨迹</el-radio-button>
        </el-radio-group>
        <AgentRunStatus :phase="currentStream.phase" :detail="currentStream.phaseDetail" />
      </div>

      <MessageList
        v-show="mode === 'chat'"
        :messages="chat.currentMessages"
        :stream="currentStream"
        :loading="chat.messagesLoading"
        @rollback="onRollback"
      />

      <CheckpointRestoreDialog
        v-if="restoreTarget && chat.currentId"
        v-model="restoreVisible"
        :conversation-id="chat.currentId"
        :target="restoreTarget"
        @completed="onRestoreCompleted"
      />

      <div v-if="mode === 'chat' && chat.messagesError" class="stream-error" role="alert">
        <span>消息加载失败：{{ chat.messagesError }}</span>
        <button type="button" class="recovery-btn" @click="chat.currentId && chat.loadMessages(chat.currentId)">重试加载</button>
      </div>

      <div v-if="mode === 'chat' && currentStream.phase === 'reconnecting'" class="stream-error" role="status">
        <span>连接中断，正在重新连接…</span>
      </div>
      <RollbackUndoBanner
        v-if="mode === 'chat' && rollbackUndo"
        :operation-id="rollbackUndo.operationId"
        @undo="onUndoRollback"
      />

      <div
        v-else-if="mode === 'chat' && (currentStream.phase === 'disconnected' || currentStream.phase === 'background_running')"
        class="stream-error"
        role="alert"
      >
        <span>{{ currentStream.phase === 'disconnected' ? '连接已断开' : '任务仍在后台执行' }}</span>
        <span class="stream-error-actions">
          <button type="button" class="recovery-btn primary" @click="stream.reconnect()">重新连接</button>
        </span>
      </div>
      <div v-else-if="mode === 'chat' && currentStream.phase === 'recoverable'" class="stream-error" role="alert">
        <span>任务执行中断，可从断点继续</span>
        <span class="stream-error-actions">
          <button type="button" class="recovery-btn primary" @click="stream.recover()">从断点继续</button>
          <button v-if="lastFailedDraft" type="button" class="recovery-btn" @click="retryFailed">
            重新执行（可能重复操作）
          </button>
        </span>
      </div>
      <div v-else-if="mode === 'chat' && currentStream.error" class="stream-error" role="alert">
        <span>发送失败：{{ currentStream.error.message }}</span>
        <span v-if="lastFailedDraft" class="stream-error-actions">
          <button type="button" class="recovery-btn" @click="restoreDraft">恢复草稿</button>
          <button v-if="currentStream.error.retryable !== false" type="button" class="recovery-btn primary" @click="retryFailed">
            重新执行（可能重复操作）
          </button>
        </span>
      </div>

      <div
        v-show="mode === 'chat'"
        class="composer"
        :class="{ dragging: isDragging }"
        @dragover.prevent="onComposerDragOver"
        @dragleave="onComposerDragLeave"
        @drop.prevent="onComposerDrop"
        @paste="onPaste"
      >
        <TransitionGroup v-if="pendingAttachments.length" tag="div" name="chip" class="composer-attachments">
          <span
            v-for="attachment in pendingAttachments"
            :key="attachment.attachment_id"
            class="composer-attachment-chip"
            :class="{ unavailable: attachment.available === false }"
            :title="attachment.available === false ? `${attachment.name}：${attachment.unavailable_reason || '不可用'}` : attachment.name"
            :aria-invalid="attachment.available === false"
          >
            <el-icon :size="14"><Picture /></el-icon>
            <span>{{ attachment.name }}</span>
            <span v-if="attachment.available === false" class="attachment-unavailable" :aria-label="attachment.unavailable_reason || '附件不可用'">不可用</span>
            <button type="button" class="chip-remove" :aria-label="`移除附件 ${attachment.name}`" @click="removeAttachment(attachment.attachment_id)">
              <el-icon :size="12"><Close /></el-icon>
            </button>
          </span>
        </TransitionGroup>
        <div class="composer-input">
          <el-input
            class="composer-textarea"
            v-model="input"
            type="textarea"
            :rows="1"
            resize="none"
            :autosize="{ minRows: 1, maxRows: 8 }"
            :maxlength="TOKEN_LIMIT"
            placeholder="输入消息，Enter 发送 / Shift+Enter 换行"
            :disabled="composerDisabled"
            @keydown="onKeydown"
          />
          <div class="composer-toolbar">
            <div class="composer-leading">
              <AttachmentUploader ref="attachmentUploader" @add="onAttach" />
            </div>
            <div class="composer-actions">
              <ModelPicker />
              <el-button
                v-if="currentStream.streaming"
                class="composer-stop"
                type="danger"
                :icon="'VideoPause'"
                :loading="currentStream.cancelling"
                :disabled="currentStream.cancelling"
                @click="stop"
              >
                {{ currentStream.cancelling ? '中断中…' : '停止' }}
              </el-button>
              <el-button
                v-else
                class="composer-submit"
                type="primary"
                :icon="'Promotion'"
                :disabled="composerDisabled || hasUnavailableAttachments || (!input.trim() && !pendingAttachments.length)"
                @click="send"
              >
                发送
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <TrajectoryPanel
        v-if="mode === 'trajectory' && chat.currentId"
        :conversation-id="chat.currentId"
        :live="currentStream.streaming"
        class="trajectory-panel"
      />
      <el-empty v-if="mode === 'trajectory' && !chat.currentId" description="请先选择会话" :image-size="60" />
    </div>

    <InterruptConfirmDialog
      :visible="interruptVisible"
      :info="currentStream.interrupted"
      :confirming="currentStream.confirming"
      @confirm="onInterruptConfirm"
    />
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  height: 100%;
  min-height: 0;
}
.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.trajectory-panel {
  flex: 1;
  min-height: 0;
}
.chat-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: var(--app-content-bg);
  border-bottom: 1px solid var(--app-border);
}
/* 会话|轨迹 tab（radio-button）：统一圆角 + hover 反馈（不碰配色） */
.chat-toolbar :deep(.el-radio-button__inner) {
  border-radius: var(--app-radius);
  transition: background 0.15s, color 0.15s;
}
.chat-toolbar :deep(.el-radio-button__inner:hover) {
  background: var(--app-border-light);
  color: var(--app-text-main);
}
.composer-attachments,
.stream-error-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.composer-attachments {
  margin-bottom: 6px;
}
.composer-attachment-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 240px;
  min-height: 28px;
  padding: 2px 6px;
  border: 1px solid color-mix(in srgb, var(--app-primary-fill) 28%, var(--app-border));
  border-radius: var(--app-radius-lg);
  background: color-mix(in srgb, var(--app-primary-fill) 8%, var(--app-content-bg));
  color: var(--app-text-secondary);
  font-size: 12px;
}
.composer-attachment-chip.unavailable {
  border-color: color-mix(in srgb, var(--app-danger) 48%, var(--app-border));
  background: color-mix(in srgb, var(--app-danger) 8%, var(--app-content-bg));
}
.attachment-unavailable { color: var(--app-danger); font-size: 11px; white-space: nowrap; }
.composer-attachment-chip > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chip-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--app-text-muted);
  cursor: pointer;
}
.chip-remove:hover {
  color: var(--app-danger);
  background: var(--app-bg);
}
.stream-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 16px;
  border-top: 1px solid color-mix(in srgb, var(--app-danger) 30%, var(--app-border));
  background: color-mix(in srgb, var(--app-danger) 5%, var(--app-content-bg));
  color: var(--app-danger);
  font-size: 13px;
}
.recovery-btn {
  min-height: var(--app-control-sm);
  padding: 3px 10px;
  border: 1px solid color-mix(in srgb, var(--app-danger) 40%, var(--app-border));
  border-radius: var(--app-radius);
  background: var(--app-content-bg);
  color: var(--app-danger);
  cursor: pointer;
}
.recovery-btn.primary {
  border-color: var(--app-primary-fill);
  background: var(--app-primary-fill);
  color: var(--app-on-primary);
}
@media (max-width: 768px) {
  .chat-toolbar {
    flex-wrap: wrap;
    padding: 8px 10px;
  }
  .stream-error {
    align-items: flex-start;
    flex-direction: column;
    padding: 8px 10px;
  }
}
</style>
