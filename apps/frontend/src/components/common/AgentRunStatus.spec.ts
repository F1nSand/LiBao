import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AgentRunStatus from './AgentRunStatus.vue'

describe('AgentRunStatus', () => {
  it('按阶段显示当前动作，并在运行阶段提供 status 语义', () => {
    const w = mount(AgentRunStatus, { props: { phase: 'tool', detail: 'web_search' } })
    expect(w.find('[role="status"]').exists()).toBe(true)
    expect(w.find('[role="status"]').text()).toContain('正在调用')
    expect(w.find('[role="status"]').text()).toContain('web_search')
    expect(w.find('.run-status-indicator.active').exists()).toBe(true)
  })

  it('已中断为静态终态，不再显示运行中动效', () => {
    const w = mount(AgentRunStatus, { props: { phase: 'cancelled' } })
    expect(w.find('[role="status"]').text()).toContain('已中断')
    expect(w.find('.run-status-indicator.active').exists()).toBe(false)
  })

  it('idle 不渲染状态胶囊', () => {
    const w = mount(AgentRunStatus, { props: { phase: 'idle' } })
    expect(w.find('[role="status"]').exists()).toBe(false)
  })

  it('确认恢复和工具详情使用活动文案', () => {
    const resuming = mount(AgentRunStatus, { props: { phase: 'resuming', detail: 'shell' } })
    expect(resuming.find('[role="status"]').text()).toContain('已确认，正在继续')
    expect(resuming.find('.run-status-indicator.active').exists()).toBe(true)
    const tool = mount(AgentRunStatus, { props: { phase: 'tool', detail: 'shell' } })
    expect(tool.find('[role="status"]').text()).toContain('正在执行 · shell')
  })

  it('断线重连/模型重试为活动态文案', () => {
    const reconnecting = mount(AgentRunStatus, { props: { phase: 'reconnecting' } })
    expect(reconnecting.find('[role="status"]').text()).toContain('连接中断，正在重连')
    expect(reconnecting.find('.run-status-indicator.active').exists()).toBe(true)

    const retrying = mount(AgentRunStatus, { props: { phase: 'retrying', detail: '（1/1）' } })
    expect(retrying.find('[role="status"]').text()).toContain('模型连接中断，正在从最近断点重试（1/1）')
    expect(retrying.find('.run-status-indicator.active').exists()).toBe(true)
  })

  it('后台执行/可恢复/断连为非活动态文案', () => {
    const bg = mount(AgentRunStatus, { props: { phase: 'background_running' } })
    expect(bg.find('[role="status"]').text()).toContain('任务仍在后台执行')
    expect(bg.find('.run-status-indicator.active').exists()).toBe(false)

    const recoverable = mount(AgentRunStatus, { props: { phase: 'recoverable' } })
    expect(recoverable.find('[role="status"]').text()).toContain('运行中断（可恢复）')
    expect(recoverable.find('.run-status-indicator.active').exists()).toBe(false)

    const disconnected = mount(AgentRunStatus, { props: { phase: 'disconnected' } })
    expect(disconnected.find('[role="status"]').text()).toContain('连接已断开')
    expect(disconnected.find('.run-status-indicator.active').exists()).toBe(false)
  })
})
