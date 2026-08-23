<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '@/stores/chat'
import { useChatStream } from '@/composables/useChatStream'
import { TOKEN_LIMIT } from '@/types'
import type { Message } from '@/types'
import { truncate } from '@/utils/format'
import MessageList from '@/components/business/MessageList.vue'
import TrajectoryPanel from '@/components/trajectory/TrajectoryPanel.vue'
import AttachmentUploader from '@/components/business/AttachmentUploader.vue'
import InterruptConfirmDialog from '@/components/business/InterruptConfirmDialog.vue'
import StatusTag from '@/components/common/StatusTag.vue'

/** 对话工作台（docs/02 §4 / §5）：消息流 + 流式渲染 + 工具卡 + 中断确认 + 会话|轨迹切换（单通用 Agent，无切换） */
const chat = useChatStore()
const stream = useChatStream({
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
})

/** 当前查看会话的流式状态（computed；切换会话时 useChatStream.setConversation 指向对应 entry） */
const currentStream = stream.state

const input = ref('')
const pendingAttachments = reactive<string[]>([])
const interruptVisible = ref(false)

/** 会话 | 轨迹 视图切换 */
const mode = ref<'chat' | 'trajectory'>('chat')

// 切换会话：流式状态按会话隔离（setConversation 指向该会话 entry，不 reset 后台流；清输入/附件）
watch(
  () => chat.currentId,
  (id) => {
    if (id) stream.setConversation(id)
    resetForNext()
  },
)

/** 流式中 / 中断等待中禁用输入框（done/error/stop 后自动恢复；按会话隔离——仅当前会话有流才禁） */
const composerDisabled = computed(() => currentStream.value.streaming || !!currentStream.value.interrupted)
const charCount = computed(() => input.value.length)

function resetForNext() {
  input.value = ''
  pendingAttachments.splice(0)
}

async function send() {
  const content = input.value.trim()
  if (!content || composerDisabled.value) return
  input.value = ''
  await sendWith(content, [...pendingAttachments])
  pendingAttachments.splice(0)
}

function stop() {
  stream.stop()
  resetForNext()
}

/** send() 的内容注入版 */
async function sendWith(content: string, attachments: string[] = []) {
  if (!content || composerDisabled.value) return
  if (content.length > TOKEN_LIMIT) {
    ElMessage.error(`输入超过 ${TOKEN_LIMIT} 字符上限`)
    return
  }
  // 若当前会话不存在则新建
  if (!chat.currentId) {
    await chat.createConversation(truncate(content, 20))
  } else {
    // 标题兜底：新建按钮创建的「新会话」——后端首条消息落库时已改名，本地列表同步
    // （与后端 truncate 同语义，避免一直显示「新会话」）
    const cur = chat.conversations.find((c) => c.id === chat.currentId)
    if (cur && cur.title === '新会话') cur.title = truncate(content, 20)
  }
  chat.appendUserMessage(content, [...attachments])
  const req = {
    conversation_id: chat.currentId,
    message: { content, role: 'user' as const, attachments: [...attachments] },
    stream: true as const,
  }
  await stream.start(req)
}

function onAttach(id: string) {
  if (pendingAttachments.length >= 10) {
    ElMessage.warning('每条消息最多 10 个附件')
    return
  }
  pendingAttachments.push(id)
}

// 中断 → 弹窗
watch(
  () => stream.state.value.interrupted,
  (v) => (interruptVisible.value = !!v),
)

async function onInterruptConfirm(approved: boolean) {
  interruptVisible.value = false
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
        <StatusTag :status="currentStream.status ?? ''" />
      </div>

      <MessageList
        v-show="mode === 'chat'"
        :messages="chat.currentMessages"
        :stream="currentStream"
      />

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
          <el-button v-if="currentStream.streaming" type="danger" :icon="'VideoPause'" @click="stop">
            停止
          </el-button>
          <el-button v-else type="primary" :icon="'Promotion'" :disabled="composerDisabled || !input.trim()" @click="send">
            发送
          </el-button>
        </div>
        <div class="composer-foot">
          <span class="char-count" :class="{ over: charCount > TOKEN_LIMIT }">{{ charCount }} / {{ TOKEN_LIMIT }}</span>
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
.composer :deep(.el-input__wrapper) {
  border-radius: var(--app-radius);
}
.composer :deep(.el-button) {
  border-radius: var(--app-radius);
}
.composer-foot {
  display: flex;
  justify-content: flex-end;
  margin-top: 6px;
}
.char-count {
  font-size: 11px;
  color: var(--app-text-muted);
  opacity: 0.7;
}
.char-count.over {
  color: #ef4444;
}
</style>
