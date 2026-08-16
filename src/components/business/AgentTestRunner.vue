<script setup lang="ts">
import { ref } from 'vue'
import { useChatStream } from '@/composables/useChatStream'
import MessageBubble from './MessageBubble.vue'

/** Agent 试跑（docs/02 §6.2）：POST /agents/{id}/invoke，复用流式协议 */
const props = defineProps<{ agentId: string }>()

const input = ref('')
const running = ref(false)
const stream = useChatStream()

async function run() {
  const content = input.value.trim()
  if (!content || running.value) return
  running.value = true
  input.value = ''
  try {
    await stream.start(
      {
        conversation_id: null,
        agent_id: props.agentId,
        message: { content, role: 'user' },
        stream: true,
      },
      `/api/v1/agents/${props.agentId}/invoke`,
    )
  } finally {
    running.value = false
  }
}
</script>

<template>
  <div class="runner">
    <div class="runner-input">
      <el-input
        v-model="input"
        type="textarea"
        :rows="2"
        placeholder="输入一条测试消息…"
        :disabled="running"
      />
      <el-button type="primary" :loading="running" :disabled="!input.trim()" @click="run">
        试跑
      </el-button>
    </div>
    <div v-if="stream.state.segments.length || stream.state.finished" class="runner-output">
      <MessageBubble :stream="stream.state" />
    </div>
    <div v-else class="runner-hint">发起试跑后，这里会流式显示 Agent 回复与工具调用。</div>
  </div>
</template>

<style scoped>
.runner-input {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.runner-output {
  margin-top: 12px;
  border: 1px solid var(--app-border-light);
  border-radius: var(--app-radius);
  background: var(--app-bg);
  max-height: 360px;
  overflow: auto;
}
.runner-hint {
  margin-top: 12px;
  color: var(--app-text-muted);
  font-size: var(--app-font-size-sm);
  text-align: center;
  padding: 20px 0;
}
</style>
