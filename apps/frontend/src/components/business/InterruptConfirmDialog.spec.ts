import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import InterruptConfirmDialog from './InterruptConfirmDialog.vue'

describe('InterruptConfirmDialog', () => {
  it('恢复请求进行中时锁定两个决策按钮并显示 loading', () => {
    const w = mount(InterruptConfirmDialog, {
      props: { visible: true, confirming: true, info: { node_id: 'n1', task_id: 't1' } },
      global: { stubs: { 'el-dialog': { template: '<div><slot/><slot name="footer"/></div>' }, 'el-alert': true, 'el-button': { props: ['disabled', 'loading'], template: '<button :disabled="disabled"><slot/></button>' }, JsonViewer: true } },
    })
    const buttons = w.findAll('button')
    expect(buttons).toHaveLength(2)
    expect(buttons.every((b) => b.attributes('disabled') !== undefined)).toBe(true)
    expect(w.text()).toContain('正在继续')
  })
})
