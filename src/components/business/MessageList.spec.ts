import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import type { Message } from '@/types'
import type { StreamState } from '@/composables/useChatStream'
import MessageList from './MessageList.vue'

const message: Message = {
  id: 'm1',
  conversation_id: 'c1',
  role: 'user',
  content: '历史消息',
  created_at: '2026-01-01T00:00:00Z',
}

function makeStream(partialText = '', segments: StreamState['segments'] = []): StreamState {
  return {
    taskId: null,
    messageId: null,
    conversationId: 'c1',
    segments,
    partialText,
    toolCalls: {},
    status: 'running',
    interrupted: null,
    error: null,
    finished: false,
    streaming: true,
  }
}

describe('MessageList 新内容提示', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('用户离底后内容增长显示回到底部按钮，点击后恢复贴底', async () => {
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      callback(0)
      return 1
    })
    const wrapper = mount(MessageList, {
      props: { messages: [message], stream: makeStream() },
      global: {
        stubs: {
          MessageBubble: { template: '<div />' },
          StreamSkeleton: { props: ['active'], template: '<div v-if="active" class="stream-skeleton" />' },
          ElIcon: { template: '<span><slot /></span>' },
          ArrowDown: true,
        },
      },
    })
    const list = wrapper.find('.msg-list').element as HTMLElement & { scrollTop: number; scrollHeight: number; clientHeight: number }
    Object.defineProperties(list, {
      scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 400 },
    })
    list.scrollTop = 0
    list.dispatchEvent(new Event('scroll'))
    expect(wrapper.find('.new-content-btn').exists()).toBe(false)

    await wrapper.setProps({
      stream: makeStream('新增内容', [{ kind: 'text', id: 's1', text: '新增内容' }]),
    })
    expect(wrapper.find('.new-content-btn').exists()).toBe(true)

    await wrapper.find('.new-content-btn').trigger('click')
    expect(list.scrollTop).toBe(600)
    expect(wrapper.find('.new-content-btn').exists()).toBe(false)

    await wrapper.setProps({
      stream: makeStream('继续新增', [{ kind: 'text', id: 's1', text: '继续新增' }]),
    })
    expect(wrapper.find('.new-content-btn').exists()).toBe(false)
  })
})
