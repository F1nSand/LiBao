import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AsyncState from './AsyncState.vue'

const global = {
  stubs: {
    EmptyState: { props: ['text'], template: '<div class="empty-state">{{ text }}</div>' },
    ElButton: { template: '<button><slot /></button>' },
  },
}

describe('AsyncState', () => {
  it('覆盖 loading、成功空态、不可用和成功内容', () => {
    const loading = mount(AsyncState, { props: { status: 'loading' }, global })
    expect(loading.get('[role="status"]').text()).toContain('正在加载')

    const empty = mount(AsyncState, { props: { status: 'success-empty', emptyText: '没有工具' }, global })
    expect(empty.get('.empty-state').text()).toContain('没有工具')

    const unavailable = mount(AsyncState, { props: { status: 'unavailable', unavailableText: '接口未实现' }, global })
    expect(unavailable.get('.empty-state').text()).toContain('接口未实现')

    const success = mount(AsyncState, { props: { status: 'success' }, slots: { default: '<div class="content">列表</div>' }, global })
    expect(success.get('.content').text()).toContain('列表')
  })

  it('错误态展示原因并通过 retry emit 恢复请求', async () => {
    const wrapper = mount(AsyncState, {
      props: { status: 'error', errorMessage: '服务暂不可用' },
      global,
    })

    expect(wrapper.get('[role="alert"]').text()).toContain('服务暂不可用')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })
})
