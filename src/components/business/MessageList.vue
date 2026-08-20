<script lang="ts">
/** 会话滚动位置记忆（模块级 Map，SPA 会话内存活）：新会话无记录→默认底部；翻过→恢复原位 */
const scrollPositions = new Map<string, number>()
</script>

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
 *
 * 2026-08-20：移除 .msg-row 的 content-visibility（scrollHeight 估算导致间歇不贴底/位置漂移），
 * 滚动改为确定性（scrollHeight 真实，nextTick + rAF 一次落地即可）。
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

/** 当前会话 id（滚动位置记账/恢复用）：messages[0].conversation_id 优先 */
const conversationId = computed(() => props.messages[0]?.conversation_id ?? props.stream?.conversationId ?? '')

/** 滚动跑批令牌：内容再次变化时作废旧 nextTick/rAF，防旧回调覆盖新目标 */
let scrollRun = 0
/** 当前活跃追帧 run；-1 = 无（追帧期间不记账中间 scrollTop，防初始未渲染态把位置记成 0 污染历史恢复） */
let activeRun = -1

function updatePinned(): void {
  const el = containerRef.value
  if (!el) return
  pinned.value = el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_TOLERANCE
  // 滚动即记账：切走再回时恢复原位（追帧期间跳过，最终位置由 finalize 记）
  if (activeRun === -1 && conversationId.value) scrollPositions.set(conversationId.value, el.scrollTop)
}

onMounted(() => {
  containerRef.value?.addEventListener('scroll', updatePinned, { passive: true })
})
onBeforeUnmount(() => {
  scrollRun++ // 作废挂起跑批
  containerRef.value?.removeEventListener('scroll', updatePinned)
})

// 内容变化（流式/新消息/完成）：仅当贴底时跟随（保持吸底），滚走则不动
watch(
  () => [props.messages.length, props.stream?.partialText, props.stream?.finished, props.stream?.interrupted],
  () => {
    if (pinned.value) scrollToStable('bottom')
  },
)

/**
 * 滚动到目标并稳定：scrollHeight 真实（无 content-visibility），但新内容在 paint commit 时会重置 scrollTop——
 * 用「位置稳定性」追帧（scrollTop 停在目标处连续 3 帧才停，自然跨过 paint），最多 30 帧兜底。
 */
function scrollToStable(target: 'bottom' | number): void {
  const el = containerRef.value
  if (!el) return
  const run = ++scrollRun
  let stable = 0
  let frame = 0
  activeRun = run
  const finalize = () => {
    if (run === activeRun) {
      activeRun = -1
      updatePinned() // 最新追帧结束：记最终位置 + 重算 pinned
    }
  }
  // 每轮：设目标 → 下一帧读回（post-paint，反映是否被浏览器 paint commit 重置）→ 稳定 3 帧才停
  const step = () => {
    if (run !== scrollRun) return
    const maxTop = Math.max(0, el.scrollHeight - el.clientHeight)
    const top = target === 'bottom' ? maxTop : Math.min(target, maxTop)
    el.scrollTop = top
    requestAnimationFrame(() => {
      if (run !== scrollRun) return
      const still = Math.abs(el.scrollTop - top) <= 1
      if (still) stable++
      else stable = 0
      if (stable >= 3 || ++frame >= 30) finalize()
      else step()
    })
  }
  void nextTick(() => step())
}

/** 会话加载/切换（messages 引用替换）：有滚动记录 → 恢复原位；无记录（新/没开过）→ 默认到底；与吸底跟随 watch 并存 */
watch(
  () => props.messages,
  () => {
    if (!props.messages.length) return
    const saved = conversationId.value ? scrollPositions.get(conversationId.value) : undefined
    if (saved != null) {
      pinned.value = false // 立即取消贴底，防恢复期间被内容 watch 拉回
      scrollToStable(saved)
    } else {
      scrollToStable('bottom')
    }
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
  /* 底部 96px 缓冲带：流式文本最新一行停在缓冲上方，不顶到 composer */
  padding: 8px 0 96px;
  background: var(--app-bg);
}
.msg-empty {
  text-align: center;
  padding: 60px 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-size-sm);
}
</style>
