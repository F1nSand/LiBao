<script lang="ts">
/** 会话滚动位置记忆（模块级 Map，SPA 会话内存活）：新会话无记录→默认底部；翻过→恢复原位 */
const scrollPositions = new Map<string, number>()
</script>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Message } from '@/types'
import type { StreamState } from '@/composables/useChatStream'
import StreamSkeleton from '@/components/common/StreamSkeleton.vue'
import MessageBubble from './MessageBubble.vue'

/**
 * 消息流（《02》前端设计 §6.2）：直接渲染全部消息（每页 ≤50，无需虚拟滚动；
 * 曾因虚拟滚动"实测高度→平均高度→startIndex"反馈循环导致长列表上滚抽搐）。
 * 吸底策略：**贴底跟随**——滚动在最下方时新内容自动追随；滚走则不强制拉回（内容照常生成在下方）。
 * 用滚动事件记录 pinned（真正最下方才贴底），内容变化时 pinned 才跟随——避免内容增长后误判"不在底部"。
 *
 * 2026-08-20：移除 .msg-row 的 content-visibility（scrollHeight 估算导致间歇不贴底/位置漂移），
 * 滚动改为确定性（scrollHeight 真实，nextTick + rAF 一次落地即可）。
 */
const props = defineProps<{ messages: Message[]; stream?: StreamState | null; loading?: boolean }>()
const emit = defineEmits<{ rollback: [message: Message] }>()

const containerRef = ref<HTMLElement | null>(null)

/**
 * 流式气泡：流式中显示；done 时 ChatView 的 onPersistedMessage 同步追加持久化消息，
 * 与气泡隐藏同一帧生效 → 无闪跳、无重复。
 */
const showStreamBubble = computed(
  () => !!props.stream && props.stream.segments.length > 0 && (!props.stream.finished || props.stream.phase === 'cancelled'),
)

/** 贴底跟随：滚动在最下方（±32px）视为 pinned；用户滚走即失效 */
const FOLLOW_TOLERANCE = 32
const pinned = ref(true)
const showJumpToLatest = computed(() => !pinned.value && !props.loading)

/** 当前会话 id（滚动位置记账/恢复用）：messages[0].conversation_id 优先 */
const conversationId = computed(() => props.messages[0]?.conversation_id ?? props.stream?.conversationId ?? '')

/** 滚动跑批令牌：内容再次变化时作废旧 nextTick/rAF，防旧回调覆盖新目标 */
let scrollRun = 0
/** 当前活跃追帧 run；-1 = 无（追帧期间不记账中间 scrollTop，防初始未渲染态把位置记成 0 污染历史恢复） */
let activeRun = -1
/** 追帧动画最后程序化设置的 scrollTop；用户滚动偏离它 → 视为用户意图，作废跑批 + 取消贴底 */
let lastSetTop = -1

function updatePinned(): void {
  const el = containerRef.value
  if (!el) return
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_TOLERANCE
  // 追帧进行中且用户滚动偏离动画目标：作废跑批 + 取消贴底——否则流式期每个 token 批次的
  // scrollToStable 会把用户滚走的顶部拉回底部（finalize 又把 pinned 重置 true），无法脱离底部
  if (activeRun !== -1 && lastSetTop >= 0 && Math.abs(el.scrollTop - lastSetTop) > 1) {
    scrollRun++
    activeRun = -1
    pinned.value = false
  } else {
    pinned.value = atBottom
  }
  // 滚动即记账：切走再回时恢复原位（追帧期间跳过，最终位置由 finalize 记）
  if (activeRun === -1 && conversationId.value) scrollPositions.set(conversationId.value, el.scrollTop)
}

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
      lastSetTop = -1
      updatePinned() // 最新追帧结束：记最终位置 + 重算 pinned
    }
  }
  // 每轮：设目标 → 下一帧读回（post-paint，反映是否被浏览器 paint commit 重置）→ 稳定 3 帧才停
  const step = () => {
    if (run !== scrollRun) return
    const maxTop = Math.max(0, el.scrollHeight - el.clientHeight)
    const top = target === 'bottom' ? maxTop : Math.min(target, maxTop)
    el.scrollTop = top
    lastSetTop = top
    requestAnimationFrame(() => {
      if (run !== scrollRun) return
      // 用户滚走（明显偏离目标，>32px 非 paint 微调）→ 中止追帧，不拉回
      if (Math.abs(el.scrollTop - top) > 32) {
        scrollRun++
        activeRun = -1
        lastSetTop = -1
        updatePinned() // 按用户当前位置重算 pinned（滚走=取消贴底）
        return
      }
      const still = Math.abs(el.scrollTop - top) <= 1
      if (still) stable++
      else stable = 0
      if (stable >= 3 || ++frame >= 30) finalize()
      else step()
    })
  }
  void nextTick(() => step())
}

/**
 * 应用当前会话滚动：有记录 → 恢复原位；无记录（新/没开过）→ 默认到底。
 * 挂载时消息已就绪（刷新 / 从其它路由返回 /chat 且已选中会话，或懒加载路由晚于会话选中）也会走这里——
 * 原 { immediate: true } watch 在 setup 期 containerRef 为 null 会静默跳过，导致该场景永不贴底。
 */
function applyScrollTo(): void {
  if (!props.messages.length) return
  const saved = conversationId.value ? scrollPositions.get(conversationId.value) : undefined
  if (saved != null) {
    pinned.value = false // 立即取消贴底，防恢复期间被内容 watch 拉回
    scrollToStable(saved)
  } else {
    scrollToStable('bottom')
  }
}

onMounted(() => {
  containerRef.value?.addEventListener('scroll', updatePinned, { passive: true })
  applyScrollTo()
})
onBeforeUnmount(() => {
  scrollRun++ // 作废挂起跑批
  containerRef.value?.removeEventListener('scroll', updatePinned)
})

// 内容版本号：覆盖消息追加 + 流式文本 + 工具/thinking/agent 段插入 + 完成/中断。
// 之前只监听 partialText/messages.length，漏了 segments（thinking/工具卡/agent_switch 段插入时
// scrollHeight 增长但 watch 不触发 → 流式中工具卡出现时滚动滞后一帧）。
const contentVersion = computed(
  () =>
    `${props.messages.length}|${props.stream?.segments.length ?? 0}|${props.stream?.partialText?.length ?? 0}|${props.stream?.finished ?? false}|${props.stream?.interrupted ?? false}`,
)
// 内容变化（流式/新消息/工具段/完成）：仅当贴底时跟随（保持吸底），滚走则不动
watch(contentVersion, () => {
  if (pinned.value) scrollToStable('bottom')
})

// 会话加载/切换（messages 引用替换）：恢复原位或贴底；与吸底跟随 watch 并存
watch(
  () => props.messages,
  applyScrollTo,
)

function jumpToLatest(): void {
  pinned.value = true
  scrollToStable('bottom')
}

defineExpose({ containerRef, jumpToLatest })
</script>

<template>
  <div class="msg-list-shell">
    <div ref="containerRef" class="msg-list">
      <StreamSkeleton :active="loading" />
      <div v-if="!loading && messages.length === 0 && !showStreamBubble" class="msg-empty">开始对话吧～</div>
      <template v-if="!loading">
        <div v-for="msg in messages" :key="msg.id" class="msg-row">
          <MessageBubble :message="msg" @rollback="emit('rollback', $event)" />
        </div>
        <div v-if="showStreamBubble" class="msg-row">
          <MessageBubble :stream="stream" />
        </div>
      </template>
    </div>
    <button
      v-if="showJumpToLatest"
      type="button"
      class="jump-to-latest-btn"
      title="回到底部"
      aria-label="回到底部"
      @click="jumpToLatest"
    >
      <span class="jump-to-latest-icon" aria-hidden="true" />
    </button>
  </div>
</template>

<style scoped>
.msg-list-shell {
  position: relative;
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
}
.msg-list {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  /* 底部 96px 缓冲带：流式文本最新一行停在缓冲上方，不顶到 composer */
  padding: 8px 0 96px;
  background: var(--app-bg);
}
.jump-to-latest-btn {
  position: absolute;
  z-index: var(--app-z-dropdown);
  left: 50%;
  bottom: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--app-control-touch);
  height: var(--app-control-touch);
  min-width: var(--app-control-touch);
  min-height: var(--app-control-touch);
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--app-primary-fill) 36%, var(--app-border));
  border-radius: 50%;
  background: color-mix(in srgb, var(--app-content-bg) 94%, var(--app-primary) 6%);
  box-shadow: var(--app-shadow-card);
  color: var(--app-link);
  cursor: pointer;
  transform: translateX(-50%);
  transition: transform 160ms var(--ease-out), box-shadow 160ms var(--ease-out), background 160ms var(--ease-out);
}
.jump-to-latest-icon {
  width: 0;
  height: 0;
  border-top: 8px solid currentColor;
  border-right: 6px solid transparent;
  border-left: 6px solid transparent;
}
.jump-to-latest-btn:hover {
  background: var(--app-content-bg);
  box-shadow: 0 4px 12px rgba(16, 24, 40, 0.14);
  transform: translateX(-50%) translateY(-2px);
}
.jump-to-latest-btn:focus-visible {
  outline: 2px solid var(--app-focus-ring);
  outline-offset: 2px;
}
.jump-to-latest-btn:active {
  transform: translateX(-50%) scale(0.94);
}
.msg-empty {
  text-align: center;
  padding: 60px 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-size-sm);
}
</style>
