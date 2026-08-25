import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Notification } from '@/types'
import type { SseEnvelope } from '@/types/sse'

/** mock @/api/notifications（模块级单例必须 vi.resetModules 后动态 import 取新实例） */
const { listNotifications, markRead } = vi.hoisted(() => ({
  listNotifications: vi.fn(),
  markRead: vi.fn(),
}))
vi.mock('@/api/notifications', () => ({ listNotifications, markRead }))

function makeNotification(partial: Partial<Notification> = {}): Notification {
  return {
    id: 'n1',
    title: '测试通知',
    body: '',
    level: 'info',
    read: false,
    created_at: '2026-08-25T00:00:00Z',
    ...partial,
  }
}

function paged(items: Notification[]) {
  return { items, total: items.length, page: 1, page_size: 20 }
}

describe('useNotifications（模块级单例）', () => {
  beforeEach(() => {
    vi.resetModules()
    listNotifications.mockReset()
    markRead.mockReset()
  })

  /** 每次动态 import 取新的模块实例（单例 state 被 reset） */
  async function fresh() {
    return (await import('./useNotifications')).useNotifications()
  }

  it('load 填充 items 与 unread', async () => {
    listNotifications.mockResolvedValue(paged([makeNotification(), makeNotification({ id: 'n2', read: true })]))
    const notif = await fresh()
    await notif.load()
    expect(notif.items.value).toHaveLength(2)
    expect(notif.unread.value).toBe(1)
  })

  it('load 失败静默（不抛、loading 复位）', async () => {
    listNotifications.mockRejectedValue(new Error('network'))
    const notif = await fresh()
    await expect(notif.load()).resolves.toBeUndefined()
    expect(notif.loading.value).toBe(false)
  })

  it('markReadById 置读并减 unread；重复调用幂等（已读不重复请求）', async () => {
    listNotifications.mockResolvedValue(paged([makeNotification(), makeNotification({ id: 'n2' })]))
    markRead.mockResolvedValue(makeNotification({ id: 'n1', read: true }))
    const notif = await fresh()
    await notif.load()
    expect(notif.unread.value).toBe(2)

    await notif.markReadById('n1')
    expect(notif.items.value[0].read).toBe(true)
    expect(notif.unread.value).toBe(1)
    expect(markRead).toHaveBeenCalledTimes(1)

    // 幂等：已读再调不重复请求也不减计数
    markRead.mockClear()
    await notif.markReadById('n1')
    expect(markRead).not.toHaveBeenCalled()
    expect(notif.unread.value).toBe(1)
  })

  it('applyEvent 新通知入队 + unread 增加；超 100 条有界', async () => {
    const notif = await fresh()
    const ev: SseEnvelope = {
      id: 'e1',
      seq: 1,
      type: 'notification',
      ts: 0,
      payload: makeNotification(),
    }
    notif.applyEvent(ev)
    expect(notif.items.value).toHaveLength(1)
    expect(notif.unread.value).toBe(1)

    // 有界：预填 100 条已读后新通知 push 后 pop 到 100（applyEvent 用 payload.id，非信封 id）
    const filled = Array.from({ length: 100 }, (_, i) => makeNotification({ id: `old${i}`, read: true }))
    notif.items.value = filled
    notif.unread.value = 0
    notif.applyEvent({ ...ev, payload: makeNotification({ id: 'e2' }) })
    expect(notif.items.value).toHaveLength(100)
    expect(notif.items.value[0].id).toBe('e2')
    expect(notif.unread.value).toBe(1)
  })

  it('applyEvent 忽略无 id 的脏包', async () => {
    const notif = await fresh()
    notif.applyEvent({ id: 'x', seq: 1, type: 'notification', ts: 0, payload: {} })
    expect(notif.items.value).toHaveLength(0)
    expect(notif.unread.value).toBe(0)
  })
})
