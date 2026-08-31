import type { ComposerAttachment, Message, RestoreDraft, FileRef } from '@/types'

/** 删除目标用户消息及其后续消息；找不到目标时返回原列表的浅副本。 */
export function truncateMessagesFrom(messages: Message[], messageId: string): Message[] {
  const index = messages.findIndex((message) => message.id === messageId)
  return index < 0 ? messages.slice() : messages.slice(0, index)
}

/** 将后端权威草稿转换为 composer 状态，保留不可用附件供用户处理。 */
export function toComposerDraft(draft: RestoreDraft): {
  content: string
  attachments: ComposerAttachment[]
  fileRefs: FileRef[]
} {
  return {
    content: draft.content,
    attachments: draft.attachments.map((attachment) => ({ ...attachment })),
    fileRefs: draft.file_refs.map((fileRef) => ({ ...fileRef })),
  }
}

/** 用于判断回滚操作生成的草稿是否仍未被用户编辑。 */
export function composerFingerprint(content: string, attachments: ComposerAttachment[], fileRefs: FileRef[]): string {
  return JSON.stringify([
    content,
    attachments.map((attachment) => attachment.attachment_id),
    fileRefs.map((fileRef) => fileRef.path),
  ])
}
