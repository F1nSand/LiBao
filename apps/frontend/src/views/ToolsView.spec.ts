import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { listTools, toggleTool } from '@/api/tool'
import type { ToolDefinition } from '@/types'

vi.mock('@/api/tool', () => ({
  listTools: vi.fn(),
  toggleTool: vi.fn(),
  createTool: vi.fn(),
  updateTool: vi.fn(),
  deleteTool: vi.fn(),
  testTool: vi.fn(),
  searchTools: vi.fn(),
}))

import ToolsView from './ToolsView.vue'

const mockedList = vi.mocked(listTools)
const mockedToggle = vi.mocked(toggleTool)

const disabledTool = {
  id: 'tool-disabled',
  name: 'disabled_tool',
  description: '待启用',
  tool_type: 'execution',
  enabled: false,
  meta: false,
  created_at: '2026-09-03T00:00:00Z',
} as ToolDefinition
const enabledTool = {
  id: 'tool-enabled',
  name: 'enabled_tool',
  description: '已启用',
  tool_type: 'execution',
  enabled: true,
  meta: false,
  created_at: '2026-09-02T00:00:00Z',
} as ToolDefinition
const mcpTool = {
  id: 'tool-mcp',
  name: 'gateway_search',
  description: 'MCP 搜索工具',
  tool_type: 'execution',
  enabled: true,
  meta: false,
  mcp_source: 'mcp:server-1',
  created_at: '2026-09-01T00:00:00Z',
} as ToolDefinition
const metaTool = {
  id: 'tool-meta',
  name: 'tool_search',
  description: '元工具',
  tool_type: 'perception',
  enabled: true,
  meta: true,
  mcp_source: null,
  created_at: '2026-08-31T00:00:00Z',
} as ToolDefinition

function mountPage() {
  setActivePinia(createPinia())
  return mount(ToolsView, { global: { plugins: [ElementPlus] } })
}

describe('ToolsView 批量启停', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedList.mockResolvedValue({ items: [disabledTool, enabledTool], total: 2, page: 1, page_size: 100 })
    mockedToggle.mockImplementation(async (id, enabled) => ({
      ...(id === disabledTool.id ? disabledTool : enabledTool),
      enabled,
    }))
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
  })

  it('选择工具后显示批量操作，并跳过已经处于目标状态的工具', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const checkboxes = wrapper.findAll('.el-table__body-wrapper input.el-checkbox__original')
    expect(checkboxes).toHaveLength(2)

    await checkboxes[0].setValue(true)
    await checkboxes[1].setValue(true)
    await flushPromises()

    expect(wrapper.get('[data-testid="tool-batch-bar"]').text()).toContain('已选 2 项')
    const enableButton = wrapper.findAll('button').find((button) => button.text() === '启用所选')
    await enableButton!.trigger('click')
    await flushPromises()

    expect(mockedToggle).toHaveBeenCalledTimes(1)
    expect(mockedToggle).toHaveBeenCalledWith(disabledTool.id, true)
  })

  it('工具页不再展示 MCP 注册入口', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).not.toContain('注册 MCP')
  })

  it('切换类别筛选时清空当前选择，避免操作隐藏工具', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('.el-table__body-wrapper input.el-checkbox__original')[0].setValue(true)
    await flushPromises()
    expect(wrapper.find('[data-testid="tool-batch-bar"]').exists()).toBe(true)

    await wrapper.find('input.el-radio-button__original-radio[value="meta"]').setValue(true)
    await flushPromises()

    expect(wrapper.find('[data-testid="tool-batch-bar"]').exists()).toBe(false)
  })

  it('MCP 工具显示 MCP 标签，并与元工具/常规工具筛选互斥', async () => {
    mockedList.mockResolvedValueOnce({
      items: [mcpTool, metaTool, enabledTool],
      total: 3,
      page: 1,
      page_size: 100,
    })
    const wrapper = mountPage()
    await flushPromises()

    const mcpRow = wrapper.findAll('.el-table__body-wrapper .el-table__row').find((row) => row.text().includes('gateway_search'))
    expect(mcpRow).toBeDefined()
    expect(mcpRow?.text()).toContain('MCP')

    await wrapper.find('input.el-radio-button__original-radio[value="mcp"]').setValue(true)
    await flushPromises()
    expect(wrapper.findAll('.el-table__body-wrapper .el-table__row')).toHaveLength(1)
    expect(wrapper.find('.el-table__body-wrapper').text()).toContain('gateway_search')

    await wrapper.find('input.el-radio-button__original-radio[value="regular"]').setValue(true)
    await flushPromises()
    expect(wrapper.find('.el-table__body-wrapper').text()).toContain('enabled_tool')
    expect(wrapper.find('.el-table__body-wrapper').text()).not.toContain('gateway_search')
  })
})
