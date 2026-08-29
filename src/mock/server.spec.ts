import { afterEach, describe, expect, it } from 'vitest'
import type { ChatRequest } from '@/types'
import { messages, uploadedAttachments, workspaceFileContents } from './db'
import { buildChatScript, toEnvelope, PERSISTED_TYPES } from './stream'
import { nextTaskSeq, pushTaskEvent, replayTaskEvents, subscribeTaskLog, taskLastSeq } from './task-events'

function finalMessageContent(request: ChatRequest): string {
  const done = buildChatScript(request).find((item) => item.type === 'done')
  return ((done?.payload ?? {}) as { message?: { content?: string } }).message?.content ?? ''
}

describe('mock chat attachment/file-ref semantics', () => {
  const attachmentId = 'atc_contract_nonce'
  const workspaceKey = 'ws_001|docs/nonce.md'

  afterEach(() => {
    uploadedAttachments.delete(attachmentId)
    delete workspaceFileContents[workspaceKey]
  })

  it('带文本附件时回复包含附件内容；没有附件时不凭空出现 nonce', () => {
    const nonce = 'ATTACHMENT_NONCE_20260828'
    uploadedAttachments.set(attachmentId, {
      attachment_id: attachmentId,
      name: 'nonce.txt',
      mime_type: 'text/plain',
      size: nonce.length,
      bytes: Buffer.from(nonce, 'utf-8'),
    })

    const withAttachment = finalMessageContent({
      conversation_id: 'c_001',
      message: { content: '请读取附件', role: 'user', attachments: [attachmentId] },
      stream: true,
    })
    const withoutAttachment = finalMessageContent({
      conversation_id: 'c_001',
      message: { content: '请回答', role: 'user', attachments: [] },
      stream: true,
    })

    expect(withAttachment).toContain(nonce)
    expect(withAttachment).toContain('[附件: nonce.txt | atc_contract_nonce]')
    expect(withoutAttachment).not.toContain(nonce)
  })

  it('工作区 file_ref 的正文进入 mock 回复并保留来源路径', () => {
    const nonce = 'WORKSPACE_NONCE_20260828'
    workspaceFileContents[workspaceKey] = `# 引用文件\n${nonce}`
    const content = finalMessageContent({
      conversation_id: 'c_ws1',
      workspace_id: 'ws_001',
      message: { content: '请读取文件', role: 'user', attachments: [], file_refs: [{ path: 'docs/nonce.md' }] },
      stream: true,
    })

    expect(content).toContain(nonce)
    expect(content).toContain('[工作区引用: docs/nonce.md]')
  })

  it('代码回复和大来源也遵守同一来源上下文策略', () => {
    const nonce = 'CODE_SOURCE_NONCE_20260828'
    const longText = nonce + 'x'.repeat(20_000)
    uploadedAttachments.set(attachmentId, {
      attachment_id: attachmentId,
      name: 'source.txt',
      mime_type: 'text/plain',
      size: longText.length,
      bytes: Buffer.from(longText, 'utf-8'),
    })

    const content = finalMessageContent({
      conversation_id: 'c_001',
      message: { content: '请解释代码', role: 'user', attachments: [attachmentId] },
      stream: true,
    })

    expect(content).toContain(nonce)
    expect(content).toContain('内容已按上下文预算截断')
    expect(content).not.toContain('x'.repeat(19_000))
  })

  it('终态消息只在 SSE 真正写出时落库，取消不会预写最终回复', () => {
    const conversationId = 'c_001'
    const before = messages[conversationId]?.length ?? 0
    const done = buildChatScript({
      conversation_id: conversationId,
      message: { content: '[slow]', role: 'user', attachments: [] },
      stream: true,
    }).find((item) => item.type === 'done')

    expect(messages[conversationId]?.length ?? 0).toBe(before)
    done?.onEmit?.()
    expect(messages[conversationId]?.length ?? 0).toBe(before + 1)
    messages[conversationId]?.pop()
  })
})

describe('mock 断线/失败关键词脚本', () => {
  const req = (content: string): ChatRequest => ({
    conversation_id: 'c_dis',
    message: { content, role: 'user', attachments: [] },
    stream: true,
  })

  it('[disconnect] 脚本含 destroy 断线 marker，其后仍有 done（后端续跑）', () => {
    const script = buildChatScript(req('[disconnect]'))
    const marker = script.find((item) => item.disconnectAfter)
    expect(marker).toBeDefined()
    expect(marker!.disconnectKind).toBe('destroy')
    expect(script.some((item) => item.type === 'done')).toBe(true)
  })

  it('[disconnect-first] 首帧（message_start）即断', () => {
    const script = buildChatScript(req('[disconnect-first]'))
    expect(script[0].type).toBe('message_start')
    expect(script[0].disconnectAfter).toBe(true)
  })

  it('[fail-recoverable] 末项为 error 且 recoverable=true；[fail] 为 false', () => {
    const rec = buildChatScript(req('[fail-recoverable]'))
    const recErr = rec.find((item) => item.type === 'error')?.payload as { recoverable?: boolean }
    expect(recErr.recoverable).toBe(true)

    const plain = buildChatScript(req('[fail]'))
    const plainErr = plain.find((item) => item.type === 'error')?.payload as { recoverable?: boolean }
    expect(plainErr.recoverable).toBe(false)
  })
})

describe('mock 任务事件日志', () => {
  const taskId = 'task_log_spec'

  afterEach(() => {
    replayTaskEvents(taskId, Number.MAX_SAFE_INTEGER)
  })

  it('persist 事件带递增 task_seq 并可补发；token 不持久化', () => {
    const seq1 = nextTaskSeq(taskId)
    pushTaskEvent(taskId, { id: 'a', seq: 1, task_seq: seq1, type: 'tool_call', ts: 1, payload: {} }, true)
    const seq2 = nextTaskSeq(taskId)
    pushTaskEvent(taskId, { id: 'b', seq: 2, task_seq: seq2, type: 'done', ts: 2, payload: {} }, true)
    pushTaskEvent(taskId, { id: 't', seq: 3, type: 'token', ts: 3, payload: { text: 'x' } }, false)

    expect(taskLastSeq(taskId)).toBe(seq2)
    const replayed = replayTaskEvents(taskId, seq1)
    expect(replayed.map((e) => e.type)).toEqual(['done'])
    expect(replayTaskEvents(taskId, seq2)).toHaveLength(0)
  })

  it('订阅者收到 live-tail（含 token）；退订后不再收到', () => {
    const seen: string[] = []
    const unsub = subscribeTaskLog(taskId, (env) => seen.push(env.type))
    pushTaskEvent(taskId, { id: 'c', seq: 1, task_seq: nextTaskSeq(taskId), type: 'status', ts: 1, payload: {} }, true)
    pushTaskEvent(taskId, { id: 't', seq: 2, type: 'token', ts: 2, payload: { text: 'y' } }, false)
    unsub()
    pushTaskEvent(taskId, { id: 'd', seq: 3, task_seq: nextTaskSeq(taskId), type: 'done', ts: 3, payload: {} }, true)
    expect(seen).toEqual(['status', 'token'])
  })
})

describe('mock toEnvelope / PERSISTED_TYPES', () => {
  it('带 taskSeq 时 id/task_seq 对齐；缺省保持连接内信封', () => {
    const item = { type: 'token' as const, payload: { text: 'a' }, delayMs: 0 }
    const withTs = toEnvelope(item, 1, 5)
    expect(withTs.id).toBe('task_evt_5')
    expect(withTs.task_seq).toBe(5)
    const without = toEnvelope(item, 2)
    expect(without.id).toBe('evt_2')
    expect(without.task_seq).toBeUndefined()
  })

  it('token/thinking 不在持久化集合', () => {
    expect(PERSISTED_TYPES.has('token')).toBe(false)
    expect(PERSISTED_TYPES.has('thinking')).toBe(false)
    expect(PERSISTED_TYPES.has('message_start')).toBe(true)
    expect(PERSISTED_TYPES.has('done')).toBe(true)
  })
})
