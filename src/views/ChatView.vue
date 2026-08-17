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
    // 用流式状态兜底补齐 done 消息：真实后端 done 的 message 可能缺 content（内容未就绪），
    // 直接 append 会让完成瞬间文本气泡消失。这里补 content，且不再 refreshMessages
    // （刷新按 page1 分页会截断长会话的最新消息）。服务端一致性在重进会话/刷新页面时同步。
    const m = (message ?? {}) as Partial<Message>
    const hasContent = !!(m.content ?? '').trim()
    chat.appendAssistantMessage({
      id: m.id ?? stream.state.messageId ?? `local_asst_${Date.now()}`,
      conversation_id: m.conversation_id ?? chat.currentId ?? '',
      role: 'assistant',
      content: hasContent ? m.content! : stream.state.partialText,
      tool_calls: m.tool_calls?.length ? m.tool_calls : undefined,
      thinking: m.thinking,
      created_at: m.created_at ?? new Date().toISOString(),
    })
  },
})

const input = ref('')
const pendingAttachments = reactive<string[]>([])
const interruptVisible = ref(false)

/** 会话 | 轨迹 视图切换 */
const mode = ref<'chat' | 'trajectory'>('chat')

// 侧栏选择会话后复位流式（用 selectionToken 区分：创建会话不递增，避免误杀刚启动的流）
watch(
  () => chat.selectionToken,
  () => {
    stream.reset()
    resetForNext()
  },
)

/** 流式中 / 中断等待中禁用输入框（done/error/stop 后自动恢复） */
const composerDisabled = computed(() => stream.state.streaming || !!stream.state.interrupted)
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
  () => stream.state.interrupted,
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
        <StatusTag :status="stream.state.status ?? ''" />
      </div>

      <MessageList
        v-show="mode === 'chat'"
        :messages="chat.currentMessages"
        :stream="stream.state"
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
          <el-button v-if="stream.state.streaming" type="danger" :icon="'VideoPause'" @click="stop">
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
        :live="stream.state.streaming"
        class="trajectory-panel"
      />
      <el-empty v-if="mode === 'trajectory' && !chat.currentId" description="请先选择会话" :image-size="60" />
    </div>

    <InterruptConfirmDialog
      :visible="interruptVisible"
      :info="stream.state.interrupted"
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
</style>
