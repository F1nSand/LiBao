import { defineComponent, h } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('@/api/workspace', () => ({
  listWorkspaceFiles: vi.fn(),
}))

import WorkspaceFileRefPicker from './WorkspaceFileRefPicker.vue'

describe('WorkspaceFileRefPicker 选择会话', () => {
  it('确认只发出叶子文件，并清理 tree checked keys', async () => {
    const checkedNodes = [
      { name: 'docs', path: 'docs', is_dir: true },
      { name: 'README.md', path: 'README.md', is_dir: false },
    ]
    const setCheckedKeys = vi.fn()
    const TreeStub = defineComponent({
      setup(_, { expose }) {
        expose({
          getCheckedNodes: () => checkedNodes,
          setCheckedKeys,
        })
        return () => h('div', { 'data-testid': 'tree' })
      },
    })

    const wrapper = mount(WorkspaceFileRefPicker, {
      props: { visible: true, workspaceId: 'ws_001' },
      global: {
        stubs: {
          'el-dialog': { template: '<div><slot /><slot name="footer" /></div>' },
          'el-tree': TreeStub,
          'el-button': { template: '<button><slot /></button>' },
          'el-icon': { template: '<span><slot /></span>' },
          Document: true,
          Folder: true,
        },
      },
    })

    await wrapper.findAll('button').at(-1)!.trigger('click')
    expect(wrapper.emitted('confirm')?.[0]?.[0]).toEqual([{ path: 'README.md' }])
    expect(setCheckedKeys).toHaveBeenCalledWith([])
    expect(wrapper.emitted('update:visible')).toEqual([[false]])
  })

  it('取消也清理上次勾选，重新打开不会复用 checked keys', async () => {
    const setCheckedKeys = vi.fn()
    const TreeStub = defineComponent({
      setup(_, { expose }) {
        expose({ getCheckedNodes: () => [], setCheckedKeys })
        return () => h('div')
      },
    })
    const wrapper = mount(WorkspaceFileRefPicker, {
      props: { visible: true, workspaceId: 'ws_001' },
      global: {
        stubs: {
          'el-dialog': { template: '<div><slot /><slot name="footer" /></div>' },
          'el-tree': TreeStub,
          'el-button': { template: '<button><slot /></button>' },
          'el-icon': { template: '<span><slot /></span>' },
          Document: true,
          Folder: true,
        },
      },
    })

    await wrapper.findAll('button').at(0)!.trigger('click')
    expect(setCheckedKeys).toHaveBeenCalledWith([])
    await wrapper.setProps({ visible: false })
    await wrapper.setProps({ visible: true })
    expect(setCheckedKeys.mock.calls.length).toBeGreaterThanOrEqual(2)
  })
})
