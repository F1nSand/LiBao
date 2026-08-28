import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const { chat, push } = vi.hoisted(() => ({
  chat: {
    conversations: [{ id: 'c1', title: '第一会话' }, { id: 'c2', title: '第二会话' }],
    currentId: 'c1',
    loadConversations: vi.fn(),
    selectConversation: vi.fn().mockResolvedValue(undefined),
    createConversation: vi.fn().mockResolvedValue(undefined),
    deleteConversation: vi.fn().mockResolvedValue(undefined),
  },
  push: vi.fn(),
}))

vi.mock('@/stores/chat', () => ({ useChatStore: () => chat }))
vi.mock('vue-router', () => ({
  useRouter: () => ({ currentRoute: { value: { path: '/chat' } }, push }),
}))

import ConversationList from './ConversationList.vue'

describe('ConversationList 键盘语义', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('会话选择使用原生 button，并暴露当前项语义', async () => {
    const wrapper = mount(ConversationList, {
      global: {
        stubs: {
          ElButton: { template: '<button><slot /></button>' },
          ElInput: { template: '<input />' },
          ElDropdown: { template: '<div><slot /><slot name="dropdown" /></div>' },
          ElDropdownMenu: { template: '<div><slot /></div>' },
          ElDropdownItem: { template: '<div><slot /></div>' },
          ElIcon: { template: '<span><slot /></span>' },
          MoreFilled: true,
          Plus: true,
          Search: true,
        },
      },
    })

    const items = wrapper.findAll('.conv-item-select')
    expect(items[0].element.tagName).toBe('BUTTON')
    expect(items[0].attributes('aria-current')).toBe('page')
    expect(items[1].attributes('aria-current')).toBeUndefined()

    await items[1].trigger('click')
    expect(chat.selectConversation).toHaveBeenCalledWith('c2')
    expect(wrapper.find('.conv-item-more').element.tagName).toBe('BUTTON')
  })
})
