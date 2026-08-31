<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useChatStream } from '@/composables/useChatStream'
import {
  listConversations,
  createConversation as apiCreateConversation,
  listMessages,
  deleteConversation as apiDeleteConversation,
} from '@/api/chat'
import { TOKEN_LIMIT } from '@/types'
import type { CheckpointAnchor, ComposerAttachment, Conversation, FileRef, Message, RestoreResult } from '@/types'
import { truncate } from '@/utils/format'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { NARROW_LAYOUT_MQ } from '@/constants/layout'
import ResourceManager from './ResourceManager.vue'
import MessageList from '@/components/business/MessageList.vue'
import TrajectoryPanel from '@/components/trajectory/TrajectoryPanel.vue'
import AttachmentUploader, { type PendingAttachment } from '@/components/business/AttachmentUploader.vue'
import InterruptConfirmDialog from '@/components/business/InterruptConfirmDialog.vue'
import AgentRunStatus from '@/components/common/AgentRunStatus.vue'
import CheckpointRestoreDialog from '@/components/business/CheckpointRestoreDialog.vue'
import ModelPicker from '@/components/business/ModelPicker.vue'
import RollbackUndoBanner from '@/components/business/RollbackUndoBanner.vue'
import { composerFingerprint, toComposerDraft, truncateMessagesFrom } from '@/utils/checkpointRestore'
import type { RestoreDialogTarget } from '@/api/checkpoints'
import WorkspaceConvList from './WorkspaceConvList.vue'
import WorkspaceFileRefPicker from './WorkspaceFileRefPicker.vue'

/**
 * 工作区内部页 shell（M7-B，《02》前端设计 §4）：左列 = 文件资源管理器（上）+ 工作区会话（下）；
 * 右侧 = 对话区（工具栏 + 消息 + composer + 轨迹）。会话状态/stream 全在此持有（不提升到详情页）。
 * 单折叠模型：左列整体收起成 28px 竖条；窗口变窄自动收、变宽自动开、手动折叠不自动开。
 */
const props = defineProps<{ workspaceId: string }>()

const stream = useChatStream({
  onCheckpointAnchor: reconcileCheckpointAnchor,
  onPersistedMessage: (m) => {
    const m0 = (m ?? {}) as Partial<Message>
    if (m0.conversation_id && m0.conversation_id !== currentId.value) return
    const hasContent = !!(m0.content ?? '').trim()
    messages.value.push({
      id: m0.id ?? stream.state.value.messageId ?? `local_asst_${Date.now()}`,
      conversation_id: m0.conversation_id ?? currentId.value ?? '',
      role: 'assistant',
      content: hasContent ? m0.content! : stream.state.value.partialText,
      tool_calls: m0.tool_calls?.length ? m0.tool_calls : undefined,
      thinking: m0.thinking,
      token_usage: m0.token_usage,
      cost: m0.cost,
      created_at: m0.created_at ?? new Date().toISOString(),
    })
  },
  onTaskSettled: ({ conversationId, status }) => {
    // 长任务断线恢复收敛 done → reload 会话消息（仅对应当前会话）
    if (conversationId && conversationId !== currentId.value) return
    if (status === 'done') void loadMessages(currentId.value ?? '')
  },
})
/** 当前工作区会话的流式状态（computed；切换会话 setConversation 指向对应 entry） */
const currentStream = stream.state

const conversations = ref<Conversation[]>([])
const currentId = ref<string | null>(null)
const messages = ref<Message[]>([])
const convLoading = ref(false)
/** 工作区会话列表请求版本：路由复用时旧工作区响应不得覆盖新列表。 */
const conversationRequestVersion = ref(0)
const messageLoading = ref(false)
const messageError = ref<string | null>(null)
/** 消息请求版本：只允许最后一次加载请求提交状态，覆盖工作区内的 A→B→A 回切竞态。 */
const messageRequestVersion = ref(0)

/** 左列（文件树 + 会话）整体折叠：窗口变窄自动收、变宽自动开；用户手动折叠不自动展开 */
const leftUserCollapsed = ref(false)
const isNarrow = useMediaQuery(NARROW_LAYOUT_MQ)
const leftCollapsed = computed(() => isNarrow.value || leftUserCollapsed.value)
function toggleLeft(): void {
  leftUserCollapsed.value = !leftUserCollapsed.value
}

const input = ref('')
const pendingAttachments = ref<ComposerAttachment[]>([])
const attachmentUploader = ref<InstanceType<typeof AttachmentUploader> | null>(null)
const isDragging = ref(false)
const lastFailedDraft = ref<{ content: string; attachments: ComposerAttachment[]; refs: FileRef[] } | null>(null)
const fileRefs = ref<FileRef[]>([])
const refPickerVisible = ref(false)
const interruptVisible = ref(false)
const restoreVisible = ref(false)
const restoreTarget = ref<RestoreDialogTarget | null>(null)
const rollbackUndo = ref<{ operationId: string; fingerprint: string } | null>(null)
/** 会话 | 轨迹 视图切换 */
const mode = ref<'chat' | 'trajectory'>('chat')

onMounted(() => {
  void loadConversations()
})

onBeforeUnmount(() => {
  conversationRequestVersion.value += 1
  messageRequestVersion.value += 1
  resetDraftForConversationChange()
  stream.stopAll() // 销毁当前 shell 的所有后台流和定时器
})

watch(
  () => props.workspaceId,
  () => {
    messageRequestVersion.value += 1
    stream.stopAll()
    restoreVisible.value = false
    restoreTarget.value = null
    rollbackUndo.value = null
    currentId.value = null
    messages.value = []
    conversations.value = []
    convLoading.value = false
    messageLoading.value = false
    messageError.value = null
    resetDraftForConversationChange()
    void loadConversations()
  },
)

async function loadConversations() {
  const requestVersion = ++conversationRequestVersion.value
  const workspaceId = props.workspaceId
  convLoading.value = true
  try {
    const res = await listConversations({ workspace_id: workspaceId, page_size: 100 })
    if (requestVersion !== conversationRequestVersion.value || workspaceId !== props.workspaceId) return
    conversations.value = res.items
  } finally {
    if (requestVersion === conversationRequestVersion.value && workspaceId === props.workspaceId) convLoading.value = false
  }
}

async function selectConversation(id: string) {
  currentId.value = id
  stream.setConversation(id)
  restoreVisible.value = false
  restoreTarget.value = null
  rollbackUndo.value = null
  resetDraftForConversationChange()
  messages.value = []
  messageError.value = null
  messageLoading.value = true
  await loadMessages(id)
}

function resetDraftForConversationChange() {
  input.value = ''
  pendingAttachments.value = []
  fileRefs.value = []
  lastFailedDraft.value = null
  refPickerVisible.value = false
  isDragging.value = false
}

async function loadMessages(id: string) {
  const requestVersion = ++messageRequestVersion.value
  messageLoading.value = true
  try {
    const res = await listMessages(id, { page_size: 100 })
    if (requestVersion !== messageRequestVersion.value || currentId.value !== id) return
    messages.value = res.items
  } catch (e) {
    if (requestVersion === messageRequestVersion.value && currentId.value === id) {
      messageError.value = e instanceof Error ? e.message : '消息加载失败'
    }
  } finally {
    if (requestVersion === messageRequestVersion.value && currentId.value === id) messageLoading.value = false
  }
}

async function createConv(title = '新会话') {
  const workspaceId = props.workspaceId
  const c = await apiCreateConversation({ title, workspace_id: props.workspaceId })
  if (workspaceId !== props.workspaceId) return
  conversations.value.unshift(c)
  await selectConversation(c.id)
}

async function deleteConv(id: string) {
  await apiDeleteConversation(id)
  conversations.value = conversations.value.filter((c) => c.id !== id)
  if (currentId.value === id) {
    messageRequestVersion.value += 1
    currentId.value = null
    resetDraftForConversationChange()
    messages.value = []
    messageLoading.value = false
    messageError.value = null
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

function addFileRefs(refs: FileRef[]) {
  const seen = new Set(fileRefs.value.map((r) => r.path))
  for (const r of refs) {
    if (!seen.has(r.path)) {
      fileRefs.value.push(r)
      seen.add(r.path)
    }
  }
}

function removeFileRef(path: string) {
  fileRefs.value = fileRefs.value.filter((r) => r.path !== path)
}

const composerDisabled = computed(() => currentStream.value.streaming || !!currentStream.value.interrupted)
const hasUnavailableAttachments = computed(() => pendingAttachments.value.some((attachment) => attachment.available === false))

async function send() {
  const content = input.value.trim()
  const attachments = [...pendingAttachments.value]
  const refs = [...fileRefs.value]
  if (hasUnavailableAttachments.value) {
    ElMessage.warning('请先移除不可用附件')
    return
  }
  if ((!content && !attachments.length && !refs.length) || composerDisabled.value) return
  input.value = ''
  pendingAttachments.value = []
  fileRefs.value = []
  await sendWith(content, attachments, refs)
}

async function sendWith(content: string, attachmentRefs: ComposerAttachment[], refs: FileRef[], appendUser = true) {
  const attachments = attachmentRefs.map((attachment) => attachment.attachment_id)
  if (attachmentRefs.some((attachment) => attachment.available === false)) {
    ElMessage.warning('请先移除不可用附件')
    return
  }
  if ((!content && !attachments.length && !refs.length) || composerDisabled.value) return
  if (content.length > TOKEN_LIMIT) {
    ElMessage.error(`输入超过 ${TOKEN_LIMIT} 字符上限`)
    return
  }
  lastFailedDraft.value = null
  try {
    if (!currentId.value) {
      await createConv(truncate(content || '附件消息', 20))
    } else {
      // 标题兜底：新建按钮创建的「新会话」——后端首条消息落库时已改名，本地列表同步
      const cur = conversations.value.find((c) => c.id === currentId.value)
      if (cur && cur.title === '新会话') cur.title = truncate(content || '附件消息', 20)
    }
    if (appendUser) {
      messages.value.push({
        id: `local_${Date.now()}`,
        conversation_id: currentId.value ?? '',
        role: 'user',
        content,
        attachments: attachmentRefs.map(({ available: _available, unavailable_reason: _reason, ...attachment }) => ({ ...attachment })),
        file_refs: refs.length ? refs : undefined,
        tool_calls: [],
        created_at: new Date().toISOString(),
      })
    }
    await stream.start({
      conversation_id: currentId.value,
      workspace_id: props.workspaceId,
      message: { content, role: 'user', attachments, file_refs: refs.length ? refs : undefined },
      stream: true,
    })
    if (currentStream.value.error) lastFailedDraft.value = { content, attachments: attachmentRefs, refs }
  } catch (e) {
    lastFailedDraft.value = { content, attachments: attachmentRefs, refs }
    ElMessage.error(e instanceof Error ? `发送失败：${e.message}` : '发送失败，请重试')
  }
}

function restoreDraft() {
  const draft = lastFailedDraft.value
  if (!draft) return
  input.value = draft.content
  pendingAttachments.value = draft.attachments.map((attachment) => ({ ...attachment }))
  fileRefs.value = draft.refs.map((fileRef) => ({ ...fileRef }))
  lastFailedDraft.value = null
}

async function retryFailed() {
  const draft = lastFailedDraft.value
  if (!draft || composerDisabled.value) return
  await sendWith(draft.content, draft.attachments, draft.refs, false)
}

function retryMessages() {
  const id = currentId.value
  if (!id) return
  messages.value = []
  messageError.value = null
  void loadMessages(id)
}

function reconcileCheckpointAnchor(anchor: CheckpointAnchor): boolean {
  if (!currentId.value || anchor.conversationId !== currentId.value) return false
  for (let index = messages.value.length - 1; index >= 0; index -= 1) {
    const message = messages.value[index]
    if (
      message.role === 'user' &&
      message.conversation_id === anchor.conversationId &&
      message.id.startsWith('local_') &&
      !message.checkpoint_id &&
      !message.checkpoint
    ) {
      message.id = anchor.userMessageId
      message.checkpoint_id = anchor.checkpointId
      return true
    }
  }
  return false
}

async function stop() {
  try {
    const result = await stream.stop()
    if (result === 'unavailable') {
      ElMessage.warning('已停止当前页面流；后端未提供可取消任务')
    }
    return result
  } catch (e) {
    ElMessage.error(e instanceof Error ? `中断失败：${e.message}` : '中断失败，请重试')
    return undefined
  }
}

async function onRollback(message: Message) {
  if (composerDisabled.value) {
    const stopResult = await stop()
    if (stopResult === 'already-finished' && currentId.value && !await stream.reconcileTaskTerminal(currentId.value)) {
      ElMessage.warning('当前任务尚未进入终态，请稍后再试')
      return
    }
    if (composerDisabled.value) {
      ElMessage.warning('当前任务尚未停止，请稍后再试')
      return
    }
  }
  const checkpointId = message.checkpoint_id ?? message.checkpoint?.id
  if (!checkpointId || !currentId.value) return
  rollbackUndo.value = null
  restoreTarget.value = { type: 'checkpoint', checkpointId, messageId: message.id }
  restoreVisible.value = true
}

function onUndoRollback() {
  const operationId = rollbackUndo.value?.operationId
  if (!operationId || !currentId.value) return
  restoreTarget.value = { type: 'rollback_operation_before', operationId }
  restoreVisible.value = true
}

async function onRestoreCompleted(result: RestoreResult) {
  const id = currentId.value
  if (!id) return
  const target = restoreTarget.value
  restoreVisible.value = false
  restoreTarget.value = null
  if (result.conversation.action === 'withdraw_from_target') {
    stream.resetConversation(id)
    if (result.conversation.withdrawn_from_message_id) {
      messages.value = truncateMessagesFrom(messages.value, result.conversation.withdrawn_from_message_id)
    }
    const draft = result.conversation.draft
    if (draft) {
      const restored = toComposerDraft(draft)
      input.value = restored.content
      pendingAttachments.value = restored.attachments
      fileRefs.value = restored.fileRefs
      rollbackUndo.value = result.undo_available
        ? { operationId: result.operation_id, fingerprint: composerFingerprint(input.value, pendingAttachments.value, fileRefs.value) }
        : null
    }
  } else if (result.conversation.action === 'restore_cursor') {
    stream.resetConversation(id)
    const baseline = rollbackUndo.value
    const currentFingerprint = composerFingerprint(input.value, pendingAttachments.value, fileRefs.value)
    if (target?.type === 'rollback_operation_before' && baseline?.operationId === target.operationId) {
      if (baseline.fingerprint === currentFingerprint) resetDraftForConversationChange()
      else ElMessage.warning('未覆盖已编辑草稿')
    }
    rollbackUndo.value = result.undo_available
      ? { operationId: result.operation_id, fingerprint: composerFingerprint(input.value, pendingAttachments.value, fileRefs.value) }
      : null
  }
  if (target?.type === 'checkpoint' && result.undo_available && !rollbackUndo.value) {
    rollbackUndo.value = { operationId: result.operation_id, fingerprint: composerFingerprint(input.value, pendingAttachments.value, fileRefs.value) }
  }
  if (result.conversation.action !== 'unchanged') await loadMessages(id)
  await loadConversations()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void send()
  }
}

// 中断 → 弹窗（按当前工作区会话）
watch(
  () => stream.state.value.interrupted,
  (v) => (interruptVisible.value = !!v),
)

async function onInterruptConfirm(approved: boolean) {
  await stream.confirmInterrupt(approved)
}
</script>

<template>
  <div class="ws-shell">
    <!-- 左列：文件树（上） + 会话（下），整体一个折叠态 -->
    <aside class="ws-left" :class="{ collapsed: leftCollapsed }">
      <Transition name="ws-fade">
        <ResourceManager v-show="!leftCollapsed" :workspace-id="workspaceId" :collapsed="leftCollapsed" @toggle="toggleLeft" />
      </Transition>
      <Transition name="ws-fade">
        <WorkspaceConvList
          v-show="!leftCollapsed"
          :items="conversations"
          :active-id="currentId"
          :loading="convLoading"
          :collapsed="leftCollapsed"
          @toggle="toggleLeft"
          @select="selectConversation"
          @create="createConv"
          @delete="deleteConv"
        />
      </Transition>
      <Transition name="ws-fade">
        <button v-show="leftCollapsed" class="ws-left-strip" type="button" title="展开侧边栏" @click="toggleLeft">
          <el-icon :size="18"><PanelLeftOpen /></el-icon>
        </button>
      </Transition>
    </aside>

    <!-- 右侧：对话区 -->
    <div class="ws-main">
      <div class="ws-toolbar">
        <el-radio-group v-model="mode" size="small">
          <el-radio-button value="chat">会话</el-radio-button>
          <el-radio-button value="trajectory" :disabled="!currentId">轨迹</el-radio-button>
        </el-radio-group>
        <AgentRunStatus :phase="currentStream.phase" :detail="currentStream.phaseDetail" />
      </div>

      <MessageList
        v-show="mode === 'chat'"
        :messages="messages"
        :stream="currentStream"
        :loading="messageLoading"
        @rollback="onRollback"
      />

      <CheckpointRestoreDialog
        v-if="restoreTarget && currentId"
        v-model="restoreVisible"
        :conversation-id="currentId"
        :target="restoreTarget"
        @completed="onRestoreCompleted"
      />

      <div v-if="mode === 'chat' && messageError" class="stream-error" role="alert">
        <span>消息加载失败：{{ messageError }}</span>
        <button type="button" class="recovery-btn" @click="retryMessages">重试加载</button>
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
        <TransitionGroup v-if="pendingAttachments.length || fileRefs.length" tag="div" name="chip" class="composer-chips">
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
          <span v-for="r in fileRefs" :key="r.path" class="composer-ref-chip" :title="r.path">
            <el-icon :size="12"><Document /></el-icon>
            <span class="mono">{{ r.path }}</span>
            <button type="button" class="chip-remove" :aria-label="`移除文件引用 ${r.path}`" @click="removeFileRef(r.path)">
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
              <span class="composer-divider" aria-hidden="true">|</span>
              <el-button :icon="'DocumentAdd'" title="引用工作区文件" aria-label="引用工作区文件" :disabled="composerDisabled" @click="refPickerVisible = true">
                引用
              </el-button>
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
                :disabled="composerDisabled || hasUnavailableAttachments || (!input.trim() && !pendingAttachments.length && !fileRefs.length)"
                @click="send"
              >
                发送
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <TrajectoryPanel
        v-if="mode === 'trajectory' && currentId"
        :conversation-id="currentId"
        :live="currentStream.streaming"
        class="trajectory-panel"
      />
      <el-empty v-if="mode === 'trajectory' && !currentId" description="请先选择会话" :image-size="60" />
    </div>

    <InterruptConfirmDialog
      :visible="interruptVisible"
      :info="currentStream.interrupted"
      :confirming="currentStream.confirming"
      @confirm="onInterruptConfirm"
    />
    <WorkspaceFileRefPicker
      :key="workspaceId"
      v-model:visible="refPickerVisible"
      :workspace-id="workspaceId"
      @confirm="addFileRefs"
    />
  </div>
</template>

<style scoped>
.ws-shell {
  display: flex;
  height: 100%;
  min-height: 0;
}
.ws-left {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--app-border);
  background: var(--app-content-bg);
  transition: width 0.2s var(--ease-out);
  overflow: hidden;
}
.ws-left.collapsed {
  width: 28px;
}
/* 左列内容折叠/展开淡入淡出（v-show 由 Transition 接管；宽度过渡并行，内容收窄后期已透明） */
.ws-fade-enter-active,
.ws-fade-leave-active {
  transition: opacity 0.15s var(--ease-out);
}
.ws-fade-enter-from,
.ws-fade-leave-to {
  opacity: 0;
}
.ws-left :deep(.rm-root) {
  flex: 1;
  min-height: 0;
  width: 100%;
}
.ws-left :deep(.ws-conv-list) {
  flex: 1;
  min-height: 0;
  width: 100%;
}
.ws-left-strip {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--app-text-muted);
  transition: color 0.2s var(--ease-out), background 0.2s var(--ease-out), opacity 0.15s var(--ease-out),
    transform 160ms var(--ease-out);
}
.ws-left-strip:hover {
  color: var(--app-primary);
  background: var(--app-bg);
}
.ws-left-strip:active {
  transform: scale(0.97);
}
.ws-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.ws-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: var(--app-content-bg);
  border-bottom: 1px solid var(--app-border);
  flex-shrink: 0;
}
/* 会话|轨迹 tab（radio-button）：统一圆角 + hover 反馈（不碰配色） */
.ws-toolbar :deep(.el-radio-button__inner) {
  border-radius: var(--app-radius);
  transition: background 0.15s, color 0.15s;
}
.ws-toolbar :deep(.el-radio-button__inner:hover) {
  background: var(--app-border-light);
  color: var(--app-text-main);
}
.trajectory-panel {
  flex: 1;
  min-height: 0;
}
.composer-chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-bottom: 6px;
}
.composer-attachment-chip,
.composer-ref-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 28px;
  padding: 2px 6px;
  border-radius: var(--app-radius-lg);
  font-size: 12px;
}
.composer-attachment-chip {
  max-width: 240px;
  border: 1px solid color-mix(in srgb, var(--app-primary-fill) 28%, var(--app-border));
  background: color-mix(in srgb, var(--app-primary-fill) 8%, var(--app-content-bg));
  color: var(--app-text-secondary);
}
.composer-attachment-chip.unavailable {
  border-color: color-mix(in srgb, var(--app-danger) 48%, var(--app-border));
  background: color-mix(in srgb, var(--app-danger) 8%, var(--app-content-bg));
}
.attachment-unavailable { color: var(--app-danger); font-size: 11px; white-space: nowrap; }
.composer-attachment-chip > span,
.composer-ref-chip > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.composer-ref-chip {
  background: color-mix(in srgb, var(--app-primary) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--app-primary) 28%, transparent);
  color: var(--app-primary);
  max-width: 260px;
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
.stream-error-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
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
/* 引用 chip 增删过渡（emil：0.15s ease-out，可中断） */
.chip-enter-active,
.chip-leave-active {
  transition: opacity 0.15s var(--ease-out), transform 0.15s var(--ease-out);
}
.chip-enter-from {
  opacity: 0;
  transform: translateY(4px) scale(0.95);
}
.chip-leave-to {
  opacity: 0;
  transform: scale(0.9);
}
.chip-move {
  transition: transform 0.15s var(--ease-out);
}
.mono {
  font-family: var(--app-font-mono);
}

@media (max-width: 768px) {
  .ws-toolbar {
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
