import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import RollbackUndoBanner from './RollbackUndoBanner.vue'

describe('RollbackUndoBanner', () => {
  it('exposes an accessible undo action and emits the operation rollback request', async () => {
    const wrapper = mount(RollbackUndoBanner, { props: { operationId: 'op_1' } })
    expect(wrapper.get('[role="status"]').text()).toContain('本次回滚已完成')
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('undo')).toHaveLength(1)
  })
})
