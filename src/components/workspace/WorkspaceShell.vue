<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useChatStream } from '@/composables/useChatStream'
import {
  listConversations,
  createConversation as apiCreateConversation,
  listMessages,
  deleteConversation as apiDeleteConversation,
} from '@/api/chat'
import { TOKEN_LIMIT } from '@/types'
import type { Conversation, FileRef, Message } from '@/types'
import { truncate } from '@/utils/format'
import { useMediaQuery } from '@/composables/useMediaQuery'
import { NARROW_LAYOUT_MQ } from '@/constants/layout'
import ResourceManager from './ResourceManager.vue'
import MessageList from '@/components/business/MessageList.vue'
import TrajectoryPanel from '@/components/trajectory/TrajectoryPanel.vue'
import AttachmentUploader from '@/components/business/AttachmentUploader.vue'
import InterruptConfirmDialog from '@/components/business/InterruptConfirmDialog.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import WorkspaceConvList from './WorkspaceConvList.vue'
import WorkspaceFileRefPicker from './WorkspaceFileRefPicker.vue'

/**
 * 工作区内部页 shell（M7-B，docs/02 §4）：左列 = 文件资源管理器（上）+ 工作区会话（下）；
 * 右侧 = 对话区（工具栏 + 消息 + composer + 轨迹）。会话状态/stream 全在此持有（不提升到详情页）。
 * 单折叠模型：左列整体收起成 28px 竖条；窗口变窄自动收、变宽自动开、手动折叠不自动开。
 */
const props = defineProps<{ workspaceId: string }>()

const stream = useChatStream({
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
})
/** 当前工作区会话的流式状态（computed；切换会话 setConversation 指向对应 entry） */
const currentStream = stream.state

const conversations = ref<Conversation[]>([])
const currentId = ref<string | null>(null)
const messages = ref<Message[]>([])
const convLoading = ref(false)

/** 左列（文件树 + 会话）整体折叠：窗口变窄自动收、变宽自动开；用户手动折叠不自动展开 */
const leftUserCollapsed = ref(false)
const isNarrow = useMediaQuery(NARROW_LAYOUT_MQ)
const leftCollapsed = computed(() => isNarrow.value || leftUserCollapsed.value)
function toggleLeft(): void {
  leftUserCollapsed.value = !leftUserCollapsed.value
}

const input = ref('')
const pendingAttachments = reactive<string[]>([])
const fileRefs = ref<FileRef[]>([])
const refPickerVisible = ref(false)
const interruptVisible = ref(false)
/** 会话 | 轨迹 视图切换 */
const mode = ref<'chat' | 'trajectory'>('chat')

onMounted(() => {
  void loadConversations()
})

onBeforeUnmount(() => {
  stream.stop() // 销毁清后台流定时器（useChatStream 第二实例）
})

async function loadConversations() {
  convLoading.value = true
  try {
    const res = await listConversations({ workspace_id: props.workspaceId, page_size: 100 })
    conversations.value = res.items
  } finally {
    convLoading.value = false
  }
}

async function selectConversation(id: string) {
  currentId.value = id
  stream.setConversation(id)
  const res = await listMessages(id, { page_size: 100 })
  if (currentId.value !== id) return // 响应序守卫
  messages.value = res.items
}

async function createConv(title = '新会话') {
  const c = await apiCreateConversation({ title, workspace_id: props.workspaceId })
  conversations.value.unshift(c)
  await selectConversation(c.id)
}

async function deleteConv(id: string) {
  await apiDeleteConversation(id)
  conversations.value = conversations.value.filter((c) => c.id !== id)
  if (currentId.value === id) {
    currentId.value = null
    messages.value = []
  }
}

function onAttach(id: string) {
  if (pendingAttachments.length >= 10) {
    ElMessage.warning('每条消息最多 10 个附件')
    return
  }
  pendingAttachments.push(id)
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
const charCount = computed(() => input.value.length)

async function send() {
  const content = input.value.trim()
  if (!content || composerDisabled.value) return
  input.value = ''
  if (!currentId.value) await createConv(truncate(content, 20))
  const attachments = [...pendingAttachments]
  const refs = [...fileRefs.value]
  pendingAttachments.splice(0)
  fileRefs.value = []
  messages.value.push({
    id: `local_${Date.now()}`,
    conversation_id: currentId.value ?? '',
    role: 'user',
    content,
    attachments: attachments.map((id) => ({ attachment_id: id })),
    file_refs: refs.length ? refs : undefined,
    tool_calls: [],
    created_at: new Date().toISOString(),
  })
  await stream.start({
    conversation_id: currentId.value,
    workspace_id: props.workspaceId,
    message: { content, role: 'user', attachments, file_refs: refs.length ? refs : undefined },
    stream: true,
  })
}

function stop() {
  stream.stop()
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
  interruptVisible.value = false
  await stream.confirmInterrupt(approved)
}
</script>

<template>
  <div class="ws-shell">
    <!-- 左列：文件树（上） + 会话（下），整体一个折叠态 -->
    <aside class="ws-left" :class="{ collapsed: leftCollapsed }">
      <ResourceManager :workspace-id="workspaceId" :collapsed="leftCollapsed" @toggle="toggleLeft" />
      <WorkspaceConvList
        :items="conversations"
        :active-id="currentId"
        :loading="convLoading"
        :collapsed="leftCollapsed"
        @toggle="toggleLeft"
        @select="selectConversation"
        @create="createConv"
        @delete="deleteConv"
      />
      <button v-show="leftCollapsed" class="ws-left-strip" type="button" title="展开侧边栏" @click="toggleLeft">
        <el-icon :size="18"><Expand /></el-icon>
      </button>
    </aside>

    <!-- 右侧：对话区 -->
    <div class="ws-main">
      <div class="ws-toolbar">
        <el-radio-group v-model="mode" size="small">
          <el-radio-button value="chat">会话</el-radio-button>
          <el-radio-button value="trajectory" :disabled="!currentId">轨迹</el-radio-button>
        </el-radio-group>
        <StatusTag :status="currentStream.status ?? ''" />
      </div>

      <MessageList v-show="mode === 'chat'" :messages="messages" :stream="currentStream" />

      <div v-show="mode === 'chat'" class="composer">
        <div class="composer-input">
          <AttachmentUploader @add="onAttach" />
          <el-input
            v-model="input"
            type="textarea"
            :rows="1"
            resize="none"
            autosize
            :maxlength="TOKEN_LIMIT"
            placeholder="输入消息，Enter 发送 / Shift+Enter 换行"
            :disabled="composerDisabled"
            @keydown="onKeydown"
          />
          <el-button :icon="'DocumentAdd'" title="引用工作区文件" :disabled="composerDisabled" @click="refPickerVisible = true">
            引用
          </el-button>
          <el-button v-if="currentStream.streaming" type="danger" :icon="'VideoPause'" @click="stop">
            停止
          </el-button>
          <el-button v-else type="primary" :icon="'Promotion'" :disabled="composerDisabled || !input.trim()" @click="send">
            发送
          </el-button>
        </div>
        <div v-if="fileRefs.length" class="composer-refs">
          <span v-for="r in fileRefs" :key="r.path" class="composer-ref-chip" :title="r.path">
            <el-icon :size="12"><Document /></el-icon>
            <span class="mono">{{ r.path }}</span>
            <el-icon :size="12" class="chip-close" @click="removeFileRef(r.path)"><Close /></el-icon>
          </span>
        </div>
        <div class="composer-foot">
          <span class="char-count" :class="{ over: charCount > TOKEN_LIMIT }">{{ charCount }} / {{ TOKEN_LIMIT }}</span>
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
      @confirm="onInterruptConfirm"
    />
    <WorkspaceFileRefPicker
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
  transition: width 0.2s ease;
  overflow: hidden;
}
.ws-left.collapsed {
  width: 28px;
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
}
.ws-left-strip:hover {
  color: var(--app-primary);
  background: var(--app-bg);
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
.trajectory-panel {
  flex: 1;
  min-height: 0;
}
.composer {
  border-top: 1px solid var(--app-border);
  background: var(--app-content-bg);
  padding: 10px 16px;
}
.composer-input {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}
.composer-refs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.composer-ref-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  background: rgba(99, 102, 241, 0.1);
  border: 1px solid rgba(99, 102, 241, 0.28);
  border-radius: 10px;
  font-size: 12px;
  color: var(--app-primary);
  max-width: 260px;
}
.composer-ref-chip .mono {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chip-close {
  cursor: pointer;
  flex-shrink: 0;
}
.chip-close:hover {
  color: #ef4444;
}
.composer-foot {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}
.char-count {
  font-size: 11px;
  color: var(--app-text-muted);
}
.char-count.over {
  color: #ef4444;
}
.mono {
  font-family: var(--app-font-mono);
}
</style>
