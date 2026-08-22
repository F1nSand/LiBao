import { describe, it, expect } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import TopBar from './TopBar.vue'

describe('TopBar（单用户本地模式）', () => {
  it('渲染 Provider 状态', () => {
    const w = shallowMount(TopBar)
    expect(w.find('.provider-status').text()).toContain('Provider 已连接')
  })

  it('渲染「本地模式」标签', () => {
    const w = shallowMount(TopBar)
    expect(w.find('.local-mode').text()).toBe('本地模式')
  })

  it('无用户头像 / 角色 / 登出下拉（单用户化后不展示用户信息）', () => {
    const w = shallowMount(TopBar)
    expect(w.find('.user-chip').exists()).toBe(false)
    expect(w.find('.user-role').exists()).toBe(false)
  })
})
