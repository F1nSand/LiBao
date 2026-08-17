<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Message } from '@/types'
import type { StreamState } from '@/composables/useChatStream'
import MessageBubble from './MessageBubble.vue'

/**
 * 消息流（docs/02 §6.2）：直接渲染全部消息（每页 ≤50，无需虚拟滚动；
 * 曾因虚拟滚动"实测高度→平均高度→startIndex"反馈循环导致长列表上滚抽搐）。
 * 吸底策略：**贴底跟随**——滚动在最下方时新内容自动追随；滚走则不强制拉回（内容照常生成在下方）。
 * 用滚动事件记录 pinned（真正最下方才贴底），内容变化时 pinned 才跟随——避免内容增长后误判"不在底部"。
 */
const props = defineProps<{ messages: Message[]; stream?: StreamState | null }>()

const containerRef = ref<HTMLElement | null>(null)

/**
 * 流式气泡：流式中显示；done 时 ChatView 的 onPersistedMessage 同步追加持久化消息，
 * 与气泡隐藏同一帧生效 → 无闪跳、无重复。
 */
const showStreamBubble = computed(() => !!props.stream && props.stream.segments.length > 0 && !props.stream.finished)

/** 贴底跟随：滚动在最下方（±32px）视为 pinned；用户滚走即失效 */
const FOLLOW_TOLERANCE = 32
const pinned = ref(true)

function updatePinned(): void {
  const el = containerRef.value
  if (!el) return
  pinned.value = el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_TOLERANCE
}

onMounted(() => {
  containerRef.value?.addEventListener('scroll', updatePinned, { passive: true })
})
onBeforeUnmount(() => {
  containerRef.value?.removeEventListener('scroll', updatePinned)
})

// 内容变化（流式/新消息/完成）：仅当贴底时跟随（保持吸底），滚走则不动
watch(
  () => [props.messages.length, props.stream?.partialText, props.stream?.finished, props.stream?.interrupted],
  () => {
    if (pinned.value) forceScrollBottom()
  },
)

/** 强制滚动到底。`.msg-row` 用 content-visibility 延迟渲染（scrollHeight 是估算值）→ 双 rAF + timeout 等真实高度后再拉 */
function forceScrollBottom(): void {
  const el = containerRef.value
  if (!el) return
  const scroll = () => {
    el.scrollTop = el.scrollHeight
  }
  void nextTick(() => {
    scroll()
    requestAnimationFrame(scroll)
    requestAnimationFrame(scroll)
    setTimeout(scroll, 60)
  })
}

/** 会话加载/切换（messages 引用替换，append 不换引用）→ 强制滚动到底，默认看最新消息；与吸底跟随 watch 并存 */
watch(
  () => props.messages,
  () => {
    if (!props.messages.length) return
    forceScrollBottom()
  },
  { immediate: true },
)

defineExpose({ containerRef })
</script>

<template>
  <div ref="containerRef" class="msg-list">
    <div v-if="messages.length === 0 && !showStreamBubble" class="msg-empty">开始对话吧～</div>
    <template v-else>
      <div v-for="msg in messages" :key="msg.id" class="msg-row">
        <MessageBubble :message="msg" />
      </div>
      <div v-if="showStreamBubble" class="msg-row">
        <MessageBubble :stream="stream" />
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
