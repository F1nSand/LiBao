import { describe, it, expect } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import TopBar from './TopBar.vue'
import type { User } from '@/types'

const baseUser: User = { id: 'u1', name: '管理员', role: 'admin' }

describe('TopBar 用户信息（数据隔离 org 显示）', () => {
  it('有 org_id 时角色行显示组织', () => {
    const w = shallowMount(TopBar, { props: { user: { ...baseUser, org_id: 'org_1' } } })
    expect(w.find('.user-role').text()).toContain('管理员')
    expect(w.find('.user-role').text()).toContain('org_1')
  })

  it('有 org_name 时优先显示名称（回退 org_id 由无 org_name 覆盖）', () => {
    const w = shallowMount(TopBar, { props: { user: { ...baseUser, org_id: 'org_1', org_name: '默认组织' } } })
    expect(w.find('.user-role').text()).toContain('默认组织')
    expect(w.find('.user-role').text()).not.toContain('org_1')
  })

  it('无 org_id 时不显示组织', () => {
    const w = shallowMount(TopBar, { props: { user: baseUser } })
    expect(w.find('.user-role').text()).toBe('管理员')
    expect(w.find('.user-role').text()).not.toContain('org_')
  })
})
