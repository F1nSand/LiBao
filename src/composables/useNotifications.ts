import { reactive, toRefs } from 'vue'
import { ElMessage } from 'element-plus'
import { listNotifications, markRead } from '@/api/notifications'
import { FEATURE, isUnavailable } from '@/api/availability'
import type { Notification } from '@/types'
import type { SseEnvelope } from '@/types/sse'

/**
 * 设置页「通知」pane 共享状态：模块级 reactive 单例（同 availability.ts 模块级 ref 先例）。
 * SSE 连接由挂载方（SettingsView）持有——useSSE 的 onScopeDispose 需要组件作用域，
 * 此处只提供 state + 纯逻辑；多组件调用共享同一实例，无重复请求。
 */
type NotificationStatus = 'idle' | 'loading' | 'success-empty' | 'success' | 'error' | 'unavailable'

const state = reactive<{ items: Notification[]; unread: number; loading: boolean; status: NotificationStatus; errorMessage: string | null }>({
  items: [],
  unread: 0,
  loading: false,
  status: 'idle',
  errorMessage: null,
})

/** 拉取通知列表（区分加载/空/失败/未实现，供设置页恢复） */
async function load() {
  if (isUnavailable(FEATURE.notifications)) {
    state.status = 'unavailable'
    return
  }
  state.loading = true
  state.status = 'loading'
  state.errorMessage = null
  try {
    const res = await listNotifications({ page: 1, page_size: 20 })
    state.items = res.items
    state.unread = res.items.filter((n) => !n.read).length
    state.status = state.items.length ? 'success' : 'success-empty'
  } catch (e) {
    state.status = isUnavailable(FEATURE.notifications) ? 'unavailable' : 'error'
    state.errorMessage = e instanceof Error ? e.message : '通知加载失败'
  } finally {
    state.loading = false
  }
}

/** 标记单条已读（幂等：已读跳过，避免重复请求/重复减计数） */
async function markReadById(id: string) {
  const n = state.items.find((x) => x.id === id)
  if (!n || n.read) return
  try {
    await markRead(id)
    n.read = true
    state.unread = Math.max(0, state.unread - 1)
  } catch (e) {
    ElMessage.error('标记已读失败')
    console.error(e)
  }
}

/** SSE 新通知入队（有界增长防长会话内存泄漏） */
function applyEvent(ev: SseEnvelope) {
  const n = ev.payload as Notification
  if (n && n.id) {
    state.items.unshift(n)
    if (state.items.length > 100) state.items.pop()
    if (!n.read) state.unread++
  }
}

export function useNotifications() {
  return { ...toRefs(state), load, markReadById, applyEvent }
}
