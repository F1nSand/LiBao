import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import { listMcpServers, registerMcp } from '@/api/mcp'
import { listTools } from '@/api/tool'
import type { McpRegisterResult, McpServer } from '@/types'

vi.mock('@/api/mcp', () => ({
  listMcpServers: vi.fn(),
  registerMcp: vi.fn(),
  deleteMcpServer: vi.fn(),
}))

vi.mock('@/api/tool', () => ({
  listTools: vi.fn(),
  toggleTool: vi.fn(),
  createTool: vi.fn(),
  updateTool: vi.fn(),
  deleteTool: vi.fn(),
  testTool: vi.fn(),
  searchTools: vi.fn(),
}))

import McpView from './McpView.vue'

const mockedList = vi.mocked(listMcpServers)
const mockedRegister = vi.mocked(registerMcp)
const mockedToolList = vi.mocked(listTools)

const server: McpServer = {
  id: 'server-1',
  name: 'my-gateway',
  transport: 'http',
  url_or_command: 'http://gateway.local/mcp',
  header_names: ['Authorization'],
  enabled: true,
  tool_count: 2,
  created_at: '2026-09-03T00:00:00Z',
}

function mountPage() {
  setActivePinia(createPinia())
  return mount(McpView, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        AsyncState: { template: '<div><slot /></div>' },
        ResponsiveDialog: {
          props: ['modelValue'],
          template: '<div v-if="modelValue" data-testid="mcp-dialog"><slot /><slot name="footer" /></div>',
        },
      },
    },
  })
}

describe('McpView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedList.mockResolvedValue([server])
    mockedToolList.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
  })

  it('展示 MCP 服务和请求头名称，但不展示请求头值', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('my-gateway')
    expect(wrapper.text()).toContain('Authorization')
    expect(wrapper.text()).not.toContain('secret-token')
  })

  it('注册时过滤空请求头并在成功后刷新 MCP 与工具列表', async () => {
    const result: McpRegisterResult = { server, tools: [] }
    mockedRegister.mockResolvedValueOnce(result)
    const wrapper = mountPage()
    await flushPromises()

    const openButton = wrapper.findAll('button').find((button) => button.text().includes('注册 MCP'))
    await openButton!.trigger('click')
    await flushPromises()
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('my-gateway')
    await inputs[1].setValue('http://gateway.local/mcp')
    await inputs[2].setValue('Authorization')
    await inputs[3].setValue('secret-token')

    const submitButton = wrapper.findAll('button').find((button) => button.text() === '注册')
    await submitButton!.trigger('click')
    await flushPromises()

    expect(mockedRegister).toHaveBeenCalledWith({
      name: 'my-gateway',
      url_or_command: 'http://gateway.local/mcp',
      headers: { Authorization: 'secret-token' },
      enable: true,
    })
    expect(mockedList).toHaveBeenCalledTimes(2)
    expect(mockedToolList).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="mcp-dialog"]').exists()).toBe(false)
  })

  it('地址为空时阻止注册请求', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const openButton = wrapper.findAll('button').find((button) => button.text().includes('注册 MCP'))
    await openButton!.trigger('click')
    const submitButton = wrapper.findAll('button').find((button) => button.text() === '注册')

    await submitButton!.trigger('click')
    expect(mockedRegister).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="mcp-dialog"]').exists()).toBe(true)
  })
})
