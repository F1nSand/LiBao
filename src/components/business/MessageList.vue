<script lang="ts">
/** 会话滚动位置记忆（模块级 Map，SPA 会话内存活）：新会话无记录→默认底部；翻过→恢复原位 */
const scrollPositions = new Map<string, number>()
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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

/** 当前会话 id（滚动位置记账/恢复用）：messages[0].conversation_id 优先 */
const conversationId = computed(() => props.messages[0]?.conversation_id ?? props.stream?.conversationId ?? '')

/** 滚动跑批状态：scrollRun 令牌作废旧跑批；autoScroll 标记程序化滚动中；settling 隐藏追帧；lastSetTop 供 handler 判别用户滚动 */
let scrollRun = 0
let autoScroll = false
let settling = false
let lastSetTop = -1

function updatePinned(): void {
  const el = containerRef.value
  if (!el) return
  pinned.value = el.scrollHeight - el.scrollTop - el.clientHeight < FOLLOW_TOLERANCE
  // 滚动即记账：切走再回时恢复原位
  if (conversationId.value) scrollPositions.set(conversationId.value, el.scrollTop)
}

/**
 * scroll 事件：循环自身程序化滚动（scrollTop === lastSetTop）忽略，不记账中间值；
 * 用户主动滚走（偏离循环目标）→ 作废跑批，恢复正常记账 + pinned 重算（保住"滚走不拉回"）。
 */
function onScroll(): void {
  const el = containerRef.value
  if (!el) return
  if (autoScroll) {
    if (el.scrollTop === lastSetTop) return
    scrollRun++
    autoScroll = false
    if (settling) {
      settling = false
      el.classList.remove('msg-list--settling')
    }
  }
  updatePinned()
}

onMounted(() => {
  containerRef.value?.addEventListener('scroll', onScroll, { passive: true })
})
onBeforeUnmount(() => {
  scrollRun++ // 作废挂起跑批
  containerRef.value?.removeEventListener('scroll', onScroll)
})

// 内容变化（流式/新消息/完成）：仅当贴底时跟随（保持吸底），滚走则不动
watch(
  () => [props.messages.length, props.stream?.partialText, props.stream?.finished, props.stream?.interrupted],
  () => {
    if (pinned.value) scrollToStable('bottom')
  },
)

/**
 * rAF 稳定循环滚动到目标。`.msg-row` 的 content-visibility 让 scrollHeight 按估算逐帧物化，
 * 固定 nextTick+双 rAF+timeout 落地会打在级联中途（闪到中间再滚到底）——
 * 改为每帧追目标，直到 scrollHeight 连续 3 帧稳定（尾部物化）再收尾。
 * hide=true（切换会话）：追帧期间 visibility:hidden，最终位置就绪后一次展示，消除闪跳。
 * 用户滚动偏离循环目标时 onScroll 作废跑批。
 */
function scrollToStable(target: 'bottom' | number, hide = false): void {
  const el = containerRef.value
  if (!el) return
  const run = ++scrollRun
  const maxTop = () => Math.max(0, el.scrollHeight - el.clientHeight)
  const want = () => (target === 'bottom' ? maxTop() : Math.min(target, maxTop()))
  if (hide && !settling) {
    settling = true
    el.classList.add('msg-list--settling')
  }
  autoScroll = true
  let lastH = -1
  let stable = 0
  let frame = 0
  let recheck = 0

  const finalize = () => {
    if (run !== scrollRun) return // 新跑批接管，不动状态
    if (recheck < 2 && el.scrollHeight !== lastH) {
      // 晚到图片/懒渲染：续追
      recheck++
      lastH = el.scrollHeight
      requestAnimationFrame(step)
      return
    }
    autoScroll = false
    lastSetTop = Math.floor(want()) // floor：scrollTop 赋值是整数，避免浮点 mismatch 误判用户滚动
    el.scrollTop = lastSetTop
    if (settling) {
      settling = false
      el.classList.remove('msg-list--settling')
    }
    updatePinned() // 唯一记账时机：最终位置 + 最终 pinned
  }

  const step = () => {
    if (run !== scrollRun) return
    lastSetTop = Math.floor(want())
    el.scrollTop = lastSetTop
    const reached =
      target === 'bottom'
        ? el.scrollTop + el.clientHeight >= el.scrollHeight - 1
        : Math.abs(el.scrollTop - want()) <= 1
    if (reached && el.scrollHeight === lastH) stable++
    else stable = 0
    lastH = el.scrollHeight
    if (stable >= 3 || ++frame >= 120) finalize()
    else requestAnimationFrame(step)
  }

  requestAnimationFrame(step)
}

/** 会话加载/切换（messages 引用替换）：有滚动记录 → 恢复原位；无记录（新/没开过）→ 默认到底；与吸底跟随 watch 并存 */
watch(
  () => props.messages,
  () => {
    if (!props.messages.length) return
    const saved = conversationId.value ? scrollPositions.get(conversationId.value) : undefined
    if (saved != null) {
      pinned.value = false // 立即取消贴底，防恢复期间被内容 watch 拉回
      scrollToStable(saved, true)
    } else {
      scrollToStable('bottom', true)
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
/* 切换会话追帧期隐藏（scrollToStable hide）：最终位置就绪后一次展示，消除"闪到中间再滚到底" */
.msg-list--settling {
  visibility: hidden;
}
/* 屏外消息跳过渲染（浏览器原生），未渲染时按 ~120px 估算高度，滚动条稳定 */
.msg-row {
  content-visibility: auto;
  contain-intrinsic-size: auto 120px;
}
</style>
