import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import type { Notification } from '@/types'

const state = vi.hoisted(() => ({
  items: [] as Notification[],
  unread: 0,
  loading: false,
  markReadById: vi.fn(),
}))

vi.mock('@/composables/useNotifications', async () => {
  const { ref } = await import('vue')
  return {
    useNotifications: () => ({
      items: ref(state.items),
      unread: ref(state.unread),
      loading: ref(state.loading),
      markReadById: state.markReadById,
    }),
  }
})

import NotificationPane from './NotificationPane.vue'

describe('NotificationPane 键盘语义', () => {
  beforeEach(() => {
    state.items.splice(0, state.items.length, {
        id: 'n1',
        title: '任务完成',
        body: '已生成结果',
        level: 'success',
        read: false,
        created_at: '2026-01-01T00:00:00Z',
    })
    state.unread = 1
    state.loading = false
    state.markReadById.mockReset()
  })

  it('通知项使用原生 button，并支持 click/键盘触发语义', async () => {
    const wrapper = mount(NotificationPane, {
      global: {
        stubs: {
          EmptyState: true,
        },
      },
    })
    const item = wrapper.find('.notif-item')
    expect(item.element.tagName).toBe('BUTTON')
    expect(item.attributes('aria-label')).toContain('任务完成')
    await item.trigger('click')
    expect(state.markReadById).toHaveBeenCalledWith('n1')
  })
})
