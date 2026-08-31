import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const { listProviders, getActiveProvider, activateProvider } = vi.hoisted(() => ({
  listProviders: vi.fn(),
  getActiveProvider: vi.fn(),
  activateProvider: vi.fn(),
}))

vi.mock('@/api/provider', () => ({ listProviders, getActiveProvider, activateProvider }))
vi.mock('@/api/availability', () => ({ FEATURE: { providers: 'available' }, isUnavailable: () => false }))

import ModelPicker from './ModelPicker.vue'

const active = { id: 'p1', name: 'OpenAI', model: 'gpt-4o', enabled: true, has_key: true }
const other = { id: 'p2', name: 'DeepSeek', model: 'deepseek-chat', enabled: false, has_key: true }

function mountPicker() {
  return mount(ModelPicker, {
    global: {
      stubs: {
        'el-popover': {
          props: ['visible'],
          emits: ['update:visible', 'show'],
          template: '<div><span data-testid="popover-reference" @click="$emit(\'update:visible\', true); $emit(\'show\')"><slot name="reference" /></span><div v-if="visible"><slot /></div></div>',
        },
        'el-button': {
          props: ['disabled'],
          template: '<button :disabled="disabled"><slot /></button>',
        },
        'el-tag': { template: '<span><slot /></span>' },
      },
    },
  })
}

describe('ModelPicker', () => {
  beforeEach(() => {
    listProviders.mockReset()
    getActiveProvider.mockReset()
    activateProvider.mockReset()
    listProviders.mockResolvedValue([active, other])
    getActiveProvider.mockResolvedValue(active)
    activateProvider.mockResolvedValue({ ...other, enabled: true })
  })

  it('loads active provider on mount and never flashes 未配置', async () => {
    let resolveActive!: (value: typeof active) => void
    getActiveProvider.mockReturnValueOnce(new Promise((resolve) => { resolveActive = resolve }))
    const wrapper = mountPicker()
    expect(wrapper.find('button').text()).toContain('加载中…')
    resolveActive(active)
    await flushPromises()
    expect(wrapper.find('button').text()).toContain('gpt-4o')
    expect(wrapper.find('button').text()).not.toContain('未配置')
    expect(listProviders).not.toHaveBeenCalled()
  })

  it('only shows 未配置 for an explicit null active provider and exposes retry on failure', async () => {
    getActiveProvider.mockResolvedValueOnce(null)
    const empty = mountPicker()
    await flushPromises()
    expect(empty.find('button').text()).toContain('未配置')

    getActiveProvider.mockRejectedValueOnce(new Error('active unavailable'))
    const failed = mountPicker()
    await flushPromises()
    expect(failed.find('button').text()).toContain('重试模型')
    await failed.find('[data-testid="popover-reference"]').trigger('click')
    expect(failed.get('[role="alert"]').text()).toContain('active unavailable')
    expect(failed.find('.model-retry').exists()).toBe(true)
  })

  it('loads provider list only on first expand and updates active badge after switching', async () => {
    const wrapper = mountPicker()
    await flushPromises()
    expect(listProviders).not.toHaveBeenCalled()
    await wrapper.find('[data-testid="popover-reference"]').trigger('click')
    await flushPromises()
    expect(listProviders).toHaveBeenCalledTimes(1)
    expect(wrapper.findAll('.model-item')).toHaveLength(2)
    await wrapper.findAll('.model-item')[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('button').text()).toContain('deepseek-chat')
    await wrapper.find('[data-testid="popover-reference"]').trigger('click')
    expect(wrapper.findAll('.model-item.active')).toHaveLength(1)
    expect(wrapper.find('.model-item.active .model-item-name').text()).toBe('DeepSeek')
  })

  it('does not let a late mount active response overwrite a newer activation', async () => {
    let resolveActive!: (value: typeof active) => void
    getActiveProvider.mockReturnValueOnce(new Promise((resolve) => { resolveActive = resolve }))
    const wrapper = mountPicker()
    await wrapper.find('[data-testid="popover-reference"]').trigger('click')
    await flushPromises()
    await wrapper.findAll('.model-item')[1].trigger('click')
    await flushPromises()
    resolveActive(active)
    await flushPromises()
    expect(wrapper.find('button').text()).toContain('deepseek-chat')
  })
})
