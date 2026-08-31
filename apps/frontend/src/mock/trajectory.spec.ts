import { describe, expect, it } from 'vitest'
import type { Message } from '@/types'
import { buildTrajectoryNodes } from './trajectory'

describe('mock 轨迹节点', () => {
  it('保留用户消息的附件与工作区引用元数据', () => {
    const message = {
      id: 'm_source',
      conversation_id: 'c_002',
      role: 'user',
      content: '',
      attachments: [{ attachment_id: 'atc_img', name: '截图.png', mime_type: 'image/png' }],
      file_refs: [{ path: 'docs/readme.md' }],
      created_at: '2026-08-28T00:00:00.000Z',
    } as Message

    const [node] = buildTrajectoryNodes('c_002', [message])

    expect(node.attachments).toEqual(message.attachments)
    expect(node.file_refs).toEqual(message.file_refs)
  })
})
