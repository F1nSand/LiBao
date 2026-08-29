import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import type { AttachmentRef } from '@/types'

import AttachmentBubble from './AttachmentBubble.vue'

const globalStubs = {
  'el-image': { template: '<img class="stub-image" />' },
  'el-icon': { template: '<span><slot /></span>' },
  Document: true,
  Download: true,
  Loading: true,
}

describe('AttachmentBubble 无分析覆盖层', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('不显示上传/分析状态，也不为每个附件启动分析轮询', async () => {
    const refs: AttachmentRef[] = [
      { attachment_id: 'atc_text', name: '说明.md', mime_type: 'text/markdown', size: 128, status: 'uploaded' },
      { attachment_id: 'atc_image', name: '截图.png', mime_type: 'image/png', size: 256, status: 'analyzing' },
      { attachment_id: 'atc_ready', name: '报告.pdf', mime_type: 'application/pdf', size: 512, status: 'ready' },
    ]
    const wrapper = mount(AttachmentBubble, { props: { refs }, global: { stubs: globalStubs } })

    expect(wrapper.find('.attach-badge').exists()).toBe(false)
    expect(wrapper.text()).not.toMatch(/待分析|分析中|已分析|分析失败/)
    expect(wrapper.text()).toContain('说明.md')
    expect(wrapper.text()).toContain('报告.pdf')

    await vi.advanceTimersByTimeAsync(10_000)
    wrapper.unmount()
  })

  it('文件卡片整体可打开附件，并展示类型与大小信息', () => {
    const wrapper = mount(AttachmentBubble, {
      props: {
        refs: [{ attachment_id: 'atc/report 1', name: '报告.pdf', mime_type: 'application/pdf', size: 2048 }],
      },
      global: { stubs: globalStubs },
    })
    const link = wrapper.find<HTMLAnchorElement>('.attach-file')
    expect(link.attributes('href')).toBe('/api/v1/attachments/atc%2Freport%201')
    expect(link.attributes('target')).toBe('_blank')
    expect(link.text()).toContain('报告.pdf')
    expect(link.text()).toContain('PDF')
    expect(link.text()).toContain('2 KB')
  })
})
