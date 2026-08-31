import { describe, expect, it } from 'vitest'
import type { RestoreDraft } from '@/types'
import { toComposerDraft, truncateMessagesFrom } from './checkpointRestore'

function msg(id: string, content = id) {
  return { id, conversation_id: 'c_1', role: 'assistant' as const, content, created_at: '2026-08-30T00:00:00.000Z' }
}

describe('checkpoint restore pure helpers', () => {
  it('truncateMessagesFrom removes the target and all following messages without mutating the source', () => {
    const messages = [msg('m_1'), msg('m_2'), msg('m_3')]
    const result = truncateMessagesFrom(messages, 'm_2')

    expect(result.map((item) => item.id)).toEqual(['m_1'])
    expect(messages.map((item) => item.id)).toEqual(['m_1', 'm_2', 'm_3'])
    expect(truncateMessagesFrom(messages, 'missing')).toEqual(messages)
  })

  it('toComposerDraft preserves attachment order/status/unavailable reason and file refs with cloned values', () => {
    const draft: RestoreDraft = {
      source_message_id: 'm_2',
      content: '原始输入',
      attachments: [
        { attachment_id: 'a_1', name: 'ready.txt', mime_type: 'text/plain', size: 4, status: 'ready', available: true },
        { attachment_id: 'a_2', name: 'missing.pdf', mime_type: 'application/pdf', size: 8, status: 'failed', available: false, unavailable_reason: '附件已过期' },
      ],
      file_refs: [{ path: 'docs/readme.md' }],
    }

    const result = toComposerDraft(draft)
    expect(result).toMatchObject({
      content: '原始输入',
      attachments: [
        { attachment_id: 'a_1', name: 'ready.txt', mime_type: 'text/plain', size: 4, status: 'ready', available: true },
        { attachment_id: 'a_2', name: 'missing.pdf', mime_type: 'application/pdf', size: 8, status: 'failed', available: false, unavailable_reason: '附件已过期' },
      ],
      fileRefs: [{ path: 'docs/readme.md' }],
    })
    expect(result.attachments[0]).not.toBe(draft.attachments[0])
    expect(result.fileRefs[0]).not.toBe(draft.file_refs[0])
    expect(result.attachments[1].available).toBe(false)
    expect(result.attachments[1].unavailable_reason).toBe('附件已过期')
  })
})
