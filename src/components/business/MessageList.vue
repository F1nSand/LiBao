<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { Message } from '@/types'
import type { StreamState } from '@/composables/useChatStream'
import MessageBubble from './MessageBubble.vue'

/**
 * 消息流（docs/02 §6.2）：直接渲染全部消息（每页 ≤50，无需虚拟滚动；
 * 曾因虚拟滚动"实测高度→平均高度→startIndex"反馈循环导致长列表上滚抽搐）。
 * 吸底策略：用户上翻时不强制滚。流式消息置底部：stream.segments 非空且未 finished 时追加一个流式气泡。
 */
const props = defineProps<{ messages: Message[]; stream?: StreamState | null }>()
const emit = defineEmits<{ retry: [] }>()

const containerRef = ref<HTMLElement | null>(null)

/**
 * 流式气泡：流式中显示；done 时 ChatView 的 onPersistedMessage 同步追加持久化消息，
 * 与气泡隐藏同一帧生效 → 无闪跳、无重复。
 */
const showStreamBubble = computed(() => !!props.stream && props.stream.segments.length > 0 && !props.stream.finished)

watch(
  () => [props.messages.length, props.stream?.partialText, props.stream?.finished, props.stream?.interrupted],
  () => {
    const el = containerRef.value
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 140
    if (nearBottom) void nextTick(() => (el.scrollTop = el.scrollHeight))
  },
)

defineExpose({ containerRef })
</script>

<template>
  <div ref="containerRef" class="msg-list">
    <div v-if="messages.length === 0 && !showStreamBubble" class="msg-empty">开始对话吧～</div>
    <template v-else>
      <div v-for="msg in messages" :key="msg.id" class="msg-row">
        <MessageBubble :message="msg" @retry="emit('retry')" />
      </div>
      <div v-if="showStreamBubble" class="msg-row">
        <MessageBubble :stream="stream" @retry="emit('retry')" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.msg-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 0;
  background: var(--app-bg);
}
.msg-empty {
  text-align: center;
  padding: 60px 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-size-sm);
}
/* 屏外消息跳过渲染（浏览器原生），未渲染时按 ~120px 估算高度，滚动条稳定 */
.msg-row {
  content-visibility: auto;
  contain-intrinsic-size: auto 120px;
}
</style>
