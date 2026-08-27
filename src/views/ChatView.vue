<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '@/stores/chat'
import { useChatStream } from '@/composables/useChatStream'
import { TOKEN_LIMIT } from '@/types'
import type { Message, ProviderConfig } from '@/types'
import { listProviders, getActiveProvider, activateProvider } from '@/api/provider'
import { FEATURE, isUnavailable } from '@/api/availability'
import { swallowNotImplemented } from '@/utils/http-envelope'
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

/* ---------- 换模型（交接板 ←后端 2026-08-27：provider 多配置唯一激活；切换只影响新对话） ---------- */
const providers = ref<ProviderConfig[]>([])
const activeProvider = ref<ProviderConfig | null>(null)
const modelMenuVisible = ref(false)
const switchingModel = ref(false)
const providerUnavailable = computed(() => isUnavailable(FEATURE.providers))

/** 按钮文案：当前生效模型名（取 model 或别名），空态「未配置」 */
const activeModelLabel = computed(() => {
  if (!activeProvider.value) return '未配置'
  return activeProvider.value.model || activeProvider.value.name
})

async function loadActiveModel() {
  const active = await swallowNotImplemented(getActiveProvider())
  if (active !== undefined) activeProvider.value = active
}

/** 首次展开选择器时拉列表（避免每次进聊天页多两个请求） */
async function onModelMenuShow() {
  if (providers.value.length) return
  await reloadProviders()
}

async function reloadProviders() {
  const list = await swallowNotImplemented(listProviders())
  if (list !== undefined) providers.value = list
  await loadActiveModel()
}

async function onPickModel(p: ProviderConfig) {
  if (p.enabled || switchingModel.value) return
  switchingModel.value = true
  try {
    const activated = await swallowNotImplemented(activateProvider(p.id))
    if (activated === undefined) return
    ElMessage.success(`已切换模型：${activated.model || activated.name}`)
    modelMenuVisible.value = false
    await reloadProviders()
  } finally {
    switchingModel.value = false
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
          <el-popover
            v-if="!providerUnavailable"
            v-model:visible="modelMenuVisible"
            placement="top-start"
            :width="300"
            trigger="click"
            popper-class="model-picker"
            @show="onModelMenuShow"
          >
            <template #reference>
              <el-button class="model-btn" :icon="'Cpu'">
                <span class="model-btn-label">{{ activeModelLabel }}</span>
              </el-button>
            </template>
            <div v-loading="switchingModel" class="model-menu">
              <div v-if="activeProvider" class="model-menu-hint">
                当前：{{ activeProvider.name }} · {{ activeProvider.model || '（未填模型名）' }}
              </div>
              <div v-else class="model-menu-hint">尚未配置 Provider（到 设置 → Provider 配置 添加）</div>
              <button
                v-for="p in providers"
                :key="p.id"
                class="model-item"
                :class="{ active: p.enabled }"
                :disabled="switchingModel"
                @click="onPickModel(p)"
              >
                <span class="model-item-name">{{ p.name }}</span>
                <span class="model-item-model">{{ p.model }}</span>
                <el-tag v-if="p.enabled" size="small" type="success">当前</el-tag>
              </button>
              <div v-if="!providers.length && !switchingModel" class="model-menu-empty">
                {{ providerUnavailable ? '' : '暂无 Provider 配置' }}
              </div>
            </div>
          </el-popover>
          <el-button
            v-if="currentStream.streaming"
            type="danger"
            :icon="'VideoPause'"
            @click="stop"
          >
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
/* 换模型按钮：弱化为次要操作（发送是主按钮），当前模型名随按钮展示 */
.model-btn {
  color: var(--app-text-secondary);
}
.model-btn-label {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

<style>
/* popover teleport 到 body → 非 scoped（对齐 el-tooltip popper-class 先例） */
.model-picker .model-menu {
  min-height: 48px;
}
.model-picker .model-menu-hint {
  margin-bottom: 6px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--app-border-light);
  color: var(--app-text-muted);
  font-size: 12px;
}
.model-picker .model-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  border-radius: var(--app-radius, 6px);
  background: transparent;
  cursor: pointer;
  text-align: left;
  font-size: 13px;
  transition: background 0.15s;
}
.model-picker .model-item:hover:not(.active) {
  background: var(--app-border-light);
}
.model-picker .model-item.active {
  cursor: default;
  background: color-mix(in srgb, var(--app-primary) 8%, transparent);
}
.model-picker .model-item-name {
  font-weight: 600;
  color: var(--app-text-main);
}
.model-picker .model-item-model {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-text-secondary);
}
.model-picker .model-menu-empty {
  padding: 12px 4px;
  text-align: center;
  color: var(--app-text-muted);
  font-size: 12px;
}
</style>
