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
    phase: 'running',
    phaseDetail: null,
    cancelling: false,
    confirming: false,
    activities: [],
    interrupted: null,
    error: null,
    finished: false,
    streaming: true,
  }
}

describe('MessageList 回到底部按钮', () => {
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
        },
      },
    })
    const list = wrapper.find('.msg-list').element as HTMLElement & { scrollTop: number; scrollHeight: number; clientHeight: number }
    Object.defineProperties(list, {
      scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 400 },
    })
    // 先让挂载时的默认贴底追帧完成，避免把测试滚动误判成初始化滚动。
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()
    list.scrollTop = 0
    list.dispatchEvent(new Event('scroll'))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.jump-to-latest-btn').exists()).toBe(true)

    await wrapper.setProps({
      stream: makeStream('新增内容', [{ kind: 'text', id: 's1', text: '新增内容' }]),
    })
    const jumpButton = wrapper.find('.jump-to-latest-btn')
    expect(jumpButton.exists()).toBe(true)
    expect(jumpButton.attributes('aria-label')).toBe('回到底部')
    expect(jumpButton.text()).toBe('')
    expect(wrapper.find('.msg-list .jump-to-latest-btn').exists()).toBe(false)

    await jumpButton.trigger('click')
    expect(list.scrollTop).toBe(600)
    expect(wrapper.find('.jump-to-latest-btn').exists()).toBe(false)

    await wrapper.setProps({
      stream: makeStream('继续新增', [{ kind: 'text', id: 's1', text: '继续新增' }]),
    })
    expect(wrapper.find('.jump-to-latest-btn').exists()).toBe(false)
  })
})
