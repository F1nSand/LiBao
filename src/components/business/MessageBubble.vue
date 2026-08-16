<script setup lang="ts">
import { computed } from 'vue'
import type { Message, ToolCallRecord } from '@/types'
import type { StreamState, ToolCallCardState } from '@/composables/useChatStream'
import MarkdownRenderer from '@/components/common/MarkdownRenderer.vue'
import ToolCallCard from './ToolCallCard.vue'
import AttachmentBubble from './AttachmentBubble.vue'

/**
 * 消息气泡（docs/02 §5.3/§5.4.3）：
 * - message：持久化消息（文本整体 + 工具卡按 position 分组，FD-12'）
 * - stream：流式实时段（text/tool 按事件序交错）
 */
const props = defineProps<{
  message?: Message
  stream?: StreamState | null
}>()
const emit = defineEmits<{ retry: [] }>()

type Seg = { kind: 'text'; content: string; streaming: boolean } | { kind: 'tool'; card: ToolCallCardState }

function fromRecord(c: ToolCallRecord): ToolCallCardState {
  return {
    tool_call_id: c.tool_call_id,
    tool_name: c.tool_name,
    input: c.input,
    structured: c.output,
    status: (c.status as ToolCallCardState['status']) ?? 'done',
    durationMs: c.duration_ms,
    startedAt: Date.now(),
  }
}

const segments = computed<Seg[]>(() => {
  if (props.stream) {
    return props.stream.segments.map((s) => {
      if (s.kind === 'text') {
        // 流式期裸文本；done 后（AgentTestRunner 等无持久化场景）切 markdown 渲染
        return { kind: 'text', content: s.text, streaming: !props.stream!.finished }
      }
      return { kind: 'tool', card: props.stream!.toolCalls[s.cardId] }
    })
  }
  const m = props.message
  if (!m) return []
  const segs: Seg[] = []
  if (m.content) segs.push({ kind: 'text', content: m.content, streaming: false })
  const calls = [...(m.tool_calls ?? [])].sort((a, b) => a.position - b.position)
  for (const c of calls) segs.push({ kind: 'tool', card: fromRecord(c) })
  return segs
})

const role = computed(() => props.stream ? 'assistant' : props.message?.role ?? 'user')
</script>

<template>
  <div class="msg" :class="role">
    <div class="msg-avatar">
      <el-avatar :size="28" :class="`avatar-${role}`">
        {{ role === 'user' ? '我' : 'AI' }}
      </el-avatar>
    </div>

    <div class="msg-content">
      <!-- 用户消息：纯文本 + 附件 -->
      <template v-if="role === 'user' && message">
        <AttachmentBubble v-if="message.attachments?.length" :refs="message.attachments" />
        <div class="msg-text user-text">{{ message.content }}</div>
      </template>

      <!-- 助手消息：段落混排 -->
      <template v-else>
        <div v-if="!segments.length && !stream" class="msg-empty">…</div>
        <div v-for="(seg, i) in segments" :key="i" class="msg-seg">
          <MarkdownRenderer v-if="seg.kind === 'text'" :raw="seg.content" :streaming="seg.streaming" />
          <ToolCallCard
            v-else
            :tool-name="seg.card.tool_name"
            :status="seg.card.status"
            :error="seg.card.error"
            @retry="emit('retry')"
          />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.msg {
  display: flex;
  gap: 10px;
  padding: 10px 16px;
}
.msg-avatar {
  flex-shrink: 0;
}
.avatar-user {
  background: var(--app-primary);
  color: #fff;
}
.avatar-assistant {
  background: #eef0f5;
  color: var(--app-text-secondary);
}
.msg-content {
  flex: 1;
  min-width: 0;
  max-width: 80%;
}
.msg.user {
  flex-direction: row-reverse;
}
.msg.user .msg-content {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.user-text {
  background: var(--app-primary);
  color: #fff;
  padding: 8px 14px;
  border-radius: 12px 12px 2px 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-width: 100%;
}
.msg:not(.user) .msg-text {
  background: #fff;
}
.msg-seg {
  background: var(--app-content-bg);
  border: 1px solid var(--app-border-light);
  border-radius: 2px 12px 12px 12px;
  padding: 8px 14px;
}
.msg-seg + .msg-seg {
  margin-top: 6px;
}
.msg-empty {
  color: var(--app-text-muted);
}
</style>
