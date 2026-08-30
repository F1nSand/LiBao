# Checkpoint 回滚正确性修复 — 前端实施计划

**状态：** `APPROVED_USER`（前端范围，2026-08-30）。用户已批准前端实施计划及本轮模型选择优化；后端 `checkpoint-restore-v2` 仍由后端 Agent 按其计划维护，未就绪前前端只能完成 mock/失败测试，不得声称真实端到端完成。

**Goal：** 修复回滚弹窗默认 Both 未真实生效、预览乱序、回滚后目标用户消息未撤回等问题；让普通会话与工作区会话在 `conversation_only` / `both` 成功后把目标用户消息的文本、附件和文件引用恢复到草稿，并从消息与轨迹中移除目标消息及其后续处理。

**Architecture：** `CheckpointRestoreDialog` 负责一次打开周期内的模式、请求版本和 preview 一致性；后端执行响应是草稿和新游标的权威来源。`ChatView` 与 `WorkspaceShell` 只负责把相同的恢复结果应用到各自 composer，随后重新加载服务端 active branch；`useChatStream` 提供按会话清理迟到流事件的窄接口。模型选择由共享 `ModelPicker` 组件消费现有 Provider API，挂载时获取 active provider，首次展开时懒加载列表，普通会话与工作区使用同一全局激活 Provider。

**本轮新增约束：**

- active provider 加载中显示“加载中…”，只有接口明确返回 `null` 才显示“未配置”；加载失败必须有可重试状态。
- 工作区 composer 左侧操作顺序固定为“选择文件 → 引用”；模型按钮占据原“引用”位置，位于发送/停止按钮左侧。
- 不新增工作区级模型字段，不复制两套 Provider 逻辑；不覆盖未确认归属的后端 `frontend_dist`。

**Frontend approver：** 前端 Agent 必须先审阅“冻结契约”和所有 Tasks，在文末审批记录中写入结论。若要求改契约，先回传后端计划同步修改，不得自行发明另一套字段。

---

## 冻结契约：`checkpoint-restore-v2`

### 模式不变量

| 模式 | 工作区文件 | 消息/轨迹 | Composer |
|---|---|---|---|
| `code_only` | 恢复 | 不变 | 不变 |
| `conversation_only` | 不变 | 删除目标用户消息及其后全部节点 | 填回目标消息草稿 |
| `both` | 恢复 | 删除目标用户消息及其后全部节点 | 填回目标消息草稿 |

- 每次打开弹窗都必须同步重置为 `both`，不能继承上次选择。
- `both` 的 radio 必须具有真实 checked 状态；默认 preview 成功后无需切换模式即可确认。
- `conversation_only` / `both` 的 `hidden_message_count` 包含目标用户消息本身。
- `both` 遇到部分文件冲突时仍撤回对话并恢复草稿；文件冲突按后端结果提示。
- 附件复用原 `attachment_id`，不重新上传；工作区 `file_refs` 同步恢复。
- 已失效附件保留在草稿中并标记不可用，用户必须移除全部不可用附件后才能重新发送；不得静默过滤、强转状态或丢弃文本/其余附件。
- `failed_partial` 不由前端按 status 猜测：始终严格应用 `result.conversation.action`。action 为 `withdraw_from_target` 时裁剪并填草稿，为 `restore_cursor` 时只重载服务端 branch，为 `unchanged` 时不动消息/composer。

### TypeScript 接口

修改 `src/types/api.ts`，新增并使用以下精确结构：

```ts
export interface RestoreDraft {
  source_message_id: string
  content: string
  attachments: RestoreDraftAttachment[]
  file_refs: FileRef[]
}

export interface RestoreDraftAttachment extends AttachmentRef {
  available: boolean
  unavailable_reason?: string | null
}

export interface ComposerAttachment {
  attachment_id: string
  name: string
  mime_type?: string
  size?: number
  status?: AttachmentStatus
  available: boolean
  unavailable_reason?: string | null
}

export interface RestoreConversationPlan {
  action: 'unchanged' | 'withdraw_from_target' | 'restore_cursor'
  active_message_head_after_id: string | null
  withdrawn_from_message_id: string | null
  hidden_message_count: number
  draft: RestoreDraft | null
}

export interface RestorePreview {
  preview_id: string
  client_request_id: string
  target: { type: 'checkpoint' | 'rollback_operation_before'; id: string; message_id?: string | null }
  mode: RollbackMode
  conversation_revision: number
  expires_at: string
  conversation: RestoreConversationPlan
  files: RestoreFilePreview[]
  warnings: string[]
}

export interface RestoreResult {
  operation_id: string
  preview_id: string
  client_request_id: string
  mode: RollbackMode
  target_message_id: string | null
  status: 'completed' | 'partial' | 'failed_partial'
  restored_files: number
  deleted_files: number
  skipped_conflicts: string[]
  conversation: RestoreConversationPlan
  undo_available: boolean
  history_revision: number
}
```

API 请求固定为判别联合：

```ts
export type RestorePreviewRequest =
  | {
      target_type: 'checkpoint'
      target_checkpoint_id: string
      mode: RollbackMode
      client_request_id: string
    }
  | {
      target_type: 'rollback_operation_before'
      target_id: string
      client_request_id: string
    }

export interface RestoreExecuteRequest {
  preview_id: string
  expected_mode: RollbackMode
  client_request_id: string
}
```

Checkpoint preview 的 mode 来自请求；operation-before 请求不携带 mode，由服务端 operation 决定并在 preview 回显。两者 execute 都使用 preview 回显的 mode 作为 `expected_mode`。

确认按钮只在以下条件全部满足时启用：

```ts
preview !== null &&
preview.mode === mode &&
preview.client_request_id === activeRequestId &&
targetMatches(preview, props.target) &&
!loading &&
!executing
```

`targetMatches` 固定规则：checkpoint target 同时校验 `preview.target.type/id/message_id` 与 `checkpointId/messageId`；operation target 校验 `preview.target.type === 'rollback_operation_before'` 且 `preview.target.id === operationId`，不要求 message id。

---

## Task 1：冻结 API 类型和 Mock 契约

**Files：**

- Modify: `src/types/api.ts:70-106`
- Modify: `src/api/checkpoints.ts:28-40`
- Modify: `src/mock/server.ts` 的 restore preview/execute handlers
- Test: `src/mock/server.spec.ts`

**Interfaces：**

- Consumes: 上述 `checkpoint-restore-v2` JSON 契约。
- Produces: `RestoreDraft`、`RestoreConversationPlan`、新版 `RestorePreview` / `RestoreResult` 与带 `client_request_id` 的请求函数。

- [ ] Step 1: 在 `server.spec.ts` 写失败测试 `returns_authoritative_draft_and_echoes_mode_request_id`，断言 preview 与 execute 同时回显 `mode/client_request_id/target.message_id`，并返回文本、附件、`file_refs`。
- [ ] Step 2: 写失败测试 `code_only_returns_unchanged_conversation_and_null_draft`。
- [ ] Step 2a: 写失败测试：失效 attachment 返回 `available=false/unavailable_reason`，operation-before 返回 `action:'restore_cursor'`。
- [ ] Step 3: 运行 `npm exec -- vitest run src/mock/server.spec.ts`，预期新增测试失败。
- [ ] Step 4: 修改类型、API 包装和 mock handler；mock 的 `hidden_message_count` 必须包含目标消息。
- [ ] Step 5: 重跑测试并执行 `npm run typecheck`，预期通过。
- [ ] Step 6: 提交 `feat(checkpoint): adopt restore v2 frontend contract`。

## Task 2：让默认 Both 成为真实选择并消除 Preview 竞态

**Files：**

- Modify: `src/components/business/CheckpointRestoreDialog.vue:1-115`
- Create: `src/components/business/CheckpointRestoreDialog.spec.ts`

**Interfaces：**

- Consumes: Task 1 的 preview/execute 接口。
- Produces: 每次打开均从 `both` 开始、只接受最新请求、确认时模式与目标强校验的弹窗。

- [ ] Step 1: 写失败测试 `opens_with_checked_both_and_confirms_without_mode_toggle`：从关闭状态打开，断言 Both 原生 radio 为 checked，请求体为 `mode:'both'`，preview 返回后可直接确认。
- [ ] Step 2: 写失败测试 `reopen_resets_previous_code_only_selection_to_both`。
- [ ] Step 3: 用 deferred promises 写失败测试 `ignores_out_of_order_preview_responses`：依次选择 `both → code_only → conversation_only`，按相反顺序 resolve，页面与执行必须只使用最后响应。
- [ ] Step 4: 写失败测试 `close_or_target_change_invalidates_inflight_preview`，旧响应不得回写。
- [ ] Step 5: 写失败测试 `cannot_confirm_when_preview_mode_request_or_message_mismatches`。
- [ ] Step 6: 运行该 spec，预期失败。
- [ ] Step 7: 将无序 `watch(mode)` 改为显式打开周期与 `selectMode(nextMode)`；每次打开同步执行 `mode='both'`、清空 preview/error、生成新 request id 并加载 Both。
- [ ] Step 8: 使用递增 `requestVersion` 或 `AbortController`；仅当前打开周期、当前目标、当前 mode 和 request id 的响应可以提交状态。旧请求的 `finally` 不得关闭新请求的 loading。
- [ ] Step 9: loading/executing 时禁用 radio、关闭和确认；执行错误 40933/40934/模式不匹配时清空旧 preview 并重新加载一次，禁止重复提交旧 ID。
- [ ] Step 10: 重跑 spec 与 typecheck，预期通过。
- [ ] Step 11: 提交 `fix(checkpoint): make restore mode selection deterministic`。

## Task 3：统一草稿恢复和消息裁剪纯逻辑

**Files：**

- Create: `src/utils/checkpointRestore.ts`
- Modify: `src/stores/chat.ts`
- Test: `src/utils/checkpointRestore.spec.ts`
- Test: `src/stores/chat.spec.ts`

**Interfaces：**

- Consumes: `RestoreConversationPlan`。
- Produces:

```ts
export function truncateMessagesFrom(messages: Message[], messageId: string): Message[]
export function toComposerDraft(draft: RestoreDraft): {
  content: string
  attachments: ComposerAttachment[]
  fileRefs: FileRef[]
}
```

- [ ] Step 1: 写失败测试：`truncateMessagesFrom` 删除目标消息及其后消息，目标不存在时不修改原数组。
- [ ] Step 2: 写失败测试：`toComposerDraft` 保留附件顺序、任意 `AttachmentStatus`、文件引用和不可用原因，不复用可变对象引用，也不把恢复附件强转为 `PendingAttachment`。
- [ ] Step 3: 在 chat store 写失败测试 `applyConversationRestore_removes_target_and_future_without_touching_other_conversation`。
- [ ] Step 4: 运行两个 spec，预期失败。
- [ ] Step 5: 实现纯函数与 store action；不得用“截断到目标后”语义。ChatView/WorkspaceShell 的 composer attachment state 统一改为 `ComposerAttachment[]`；新上传的 `PendingAttachment` 在 `onAttach` 映射为 `available=true`。
- [ ] Step 6: 重跑测试，预期通过。
- [ ] Step 7: 提交 `feat(checkpoint): model withdrawn message drafts`。

## Task 4：普通会话应用权威草稿并清理流状态

**Files：**

- Modify: `src/views/ChatView.vue:54-219`
- Modify: `src/composables/useChatStream.ts`
- Test: `src/views/ChatView.spec.ts`（若项目未有该文件则创建）
- Test: `src/composables/useChatStream.spec.ts`

**Interfaces：**

- Consumes: `completed(result: RestoreResult)` 与 Task 3 纯函数。
- Produces:

```ts
resetConversation(conversationId: string): void
reconcileTaskTerminal(conversationId: string): Promise<boolean>
```

每个会话 context 增加单调递增 `generation`。stream start/reconnect/resume 捕获 generation，所有 event、finalize、error、timer 回调在写状态前校验 generation；`resetConversation` 先递增 generation，再停止并清理 reader/reconnect timer、segments、partialText、tool cards、interrupted/cancelled 状态。仅 abort/清空状态不足以防止已排队回调回写。

- [ ] Step 1: 写失败测试：`both` 和 `conversation_only` 成功后，目标及未来消息立即消失，`input/pendingAttachments` 由 `result.conversation.draft` 回填，视图切回 chat，再加载服务端消息。
- [ ] Step 2: 写失败测试：`code_only` 不修改消息数组、composer、附件和当前 chat/trajectory 视图。
- [ ] Step 3: 写失败测试：后端返回 draft 与打开弹窗时缓存消息不同时，以后端 draft 为准。
- [ ] Step 4: 在 `useChatStream.spec.ts` 写失败测试：reset 后迟到 token/tool/done 事件不能更新该会话，composer 状态恢复 idle。
- [ ] Step 4a: 写失败测试：ChatView 在 preview/execute 期间切会话会关闭弹窗、递增 dialog request version；旧 `conversationId + client_request_id` 的完成回调不得写入新会话草稿。
- [ ] Step 4b: 写失败测试：cancel 返回 `already-finished` 时调用现有 `getTaskStatus(taskId)` 对账；仅 `done/failed/cancelled` 返回 terminal=true，仍为 pending/running/waiting_confirm 或查询失败时不得打开弹窗。
- [ ] Step 4c: 写失败测试：`failed_partial + withdraw_from_target` 仍应用权威草稿；`failed_partial + unchanged` 不裁剪消息。
- [ ] Step 4d: 写失败测试：不可用 attachment chip 显示“不可用”和 `unavailable_reason`，具有 `aria-invalid=true` 与可访问说明；发送按钮禁用，直接调用 send 也 fail-fast 并提示先移除；移除后文本和其余附件恢复可发送。
- [ ] Step 5: 运行定向测试，预期失败。
- [ ] Step 6: 打开弹窗时深拷贝目标消息仅作展示和异常兜底；完成后只以执行响应为权威数据。
- [ ] Step 7: 捕获打开时的 `conversationId + client_request_id`；切会话 watcher 必须关闭弹窗、清空 restore target 并 invalidate 请求。完成回调仅在二者仍匹配时应用。
- [ ] Step 8: 对 `action='withdraw_from_target'` 先调用 `resetConversation`，再本地裁剪/填草稿；`restore_cursor` 只 reset/reload；`unchanged` 不动 branch/composer。最后 `loadMessages/loadConversations` 权威对账；任何 reload 失败都保留已恢复草稿并显示可重试错误。
- [ ] Step 8a: `reconcileTaskTerminal` 复用 `getTaskStatus`；任务未明确进入 `done/failed/cancelled` 不得打开弹窗。
- [ ] Step 9: 重跑测试和 typecheck，预期通过。
- [ ] Step 10: 提交 `fix(chat): withdraw restored user turn into composer`。

## Task 5：WorkspaceShell 同步草稿、附件与文件引用

**Files：**

- Modify: `src/components/workspace/WorkspaceShell.vue:79-150,250-378`
- Test: `src/components/workspace/WorkspaceShell.spec.ts`

**Interfaces：**

- Consumes: Task 3 的 `toComposerDraft` 和 Task 4 的 `resetConversation`。
- Produces: 与普通会话完全相同的回滚语义，并额外恢复 `fileRefs`。

- [ ] Step 1: 写失败测试：Both/Conversation only 将后端 draft 的 `content/attachments/file_refs` 填回 workspace composer，并删除目标及以后消息。
- [ ] Step 2: 写失败测试：Code only 保持 composer、消息、file refs 不变。
- [ ] Step 3: 写失败测试：执行期间切换 workspace/conversation，旧 restore result 不得写入新会话草稿。
- [ ] Step 4: 写失败测试：rollback 后切到 trajectory，目标 USER 与之后节点均不出现。
- [ ] Step 4a: 写失败测试：`failed_partial` 按 conversation action 应用，与 ChatView 完全一致。
- [ ] Step 4b: 写失败测试：workspace composer 的不可用 attachment chip 显示状态/原因和 `aria-invalid`；发送按钮禁用、send fail-fast，移除后恢复发送。
- [ ] Step 5: 运行 spec，预期失败。
- [ ] Step 6: 在完成回调中捕获并校验 `workspaceId + conversationId + restore request id`；应用结果后重新加载对应会话与列表。
- [ ] Step 7: 重跑测试，预期通过。
- [ ] Step 8: 提交 `fix(workspace): restore withdrawn turn to workspace draft`。

## Task 6：接通回滚操作的再次回滚和草稿保护

**Files：**

- Create: `src/components/business/RollbackUndoBanner.vue`
- Modify: `src/components/business/CheckpointRestoreDialog.vue`
- Modify: `src/views/ChatView.vue`
- Modify: `src/components/workspace/WorkspaceShell.vue`
- Modify: `src/api/checkpoints.ts`
- Modify: `src/types/api.ts`
- Test: `src/components/business/RollbackUndoBanner.spec.ts`
- Test: `src/components/business/CheckpointRestoreDialog.spec.ts`

**Interfaces：**

- 将 dialog target 改为判别联合：

```ts
type RestoreDialogTarget =
  | { type: 'checkpoint'; checkpointId: string; messageId: string }
  | { type: 'rollback_operation_before'; operationId: string }
```

- 成功 restore 且 `undo_available=true` 后，composer 上方显示持久到下一次 branch 操作/切会话的 `RollbackUndoBanner`。
- operation-before preview 的模式由服务端 operation 决定，dialog 不显示可切换的三模式选择；执行仍绑定 preview mode/request id。
- 记录 `RollbackDraftBaseline = {operationId, fingerprint}`；fingerprint 由 content、按顺序 attachment ids、file-ref paths 规范化生成。

- [ ] Step 1: 写失败测试：checkpoint restore 成功后 banner 显示“撤销本次回滚”，点击用 `target_type:'rollback_operation_before'` 和 operation id 打开预览。
- [ ] Step 2: 写失败测试：operation-before 不允许切换 mode，确认执行服务端返回的 mode。
- [ ] Step 2a: 写失败测试：operation preview request 只发送 `target_type/target_id/client_request_id`；确认按 operation type/id 校验，不依赖 messageId。
- [ ] Step 3: 写失败测试：undo 恢复旧 cursor 后重新加载消息/轨迹；返回的 inverse operation 替换 banner，因此可以继续来回切换。
- [ ] Step 4: 写失败测试：当前 composer fingerprint 与 operation 生成草稿相同则 undo 后清空；用户修改过文本、附件或 file ref 时保留草稿并提示“未覆盖已编辑草稿”。
- [ ] Step 5: 写失败测试：切会话/workspace 时 baseline 隔离，旧 operation 不得清空新会话 composer。
- [ ] Step 6: 运行定向测试，预期失败。
- [ ] Step 7: 实现判别联合、banner、baseline/fingerprint 和双入口应用逻辑。
- [ ] Step 8: 重跑测试和 typecheck，预期通过。
- [ ] Step 9: 提交 `feat(checkpoint): expose reversible rollback operations`。

## Task 7：消除消息操作栏的隐藏占位

**Files：**

- Modify: `src/components/business/MessageBubble.vue:300-380`
- Modify: `src/components/business/MessageBubble.spec.ts`
- Modify: `e2e/checkpoint-rollback.spec.ts`

**Interfaces：**

- Consumes: 现有复制、回滚事件。
- Produces: 桌面端不占文档流的右下角图标操作栏；触屏继续保持至少 44×44 命中区。

- [ ] Step 1: 写失败测试或样式断言：隐藏桌面 action bar 不再保留 `min-height:30px + margin`。
- [ ] Step 2: 保留并扩展 mouseleave、`:focus-visible`、触屏命中区测试。
- [ ] Step 3: 桌面端将 action bar 绝对定位到消息 surface 右下角，并为文本保留不会覆盖最后一行的内边距；图标顺序固定为复制在右、回滚在左。
- [ ] Step 4: 运行 MessageBubble spec 与定向 Chromium E2E，预期通过。
- [ ] Step 5: 提交 `fix(chat): overlay message actions without layout gap`。

## Task 8：抽取共享 ModelPicker 并修复首次打开模型误显示

**Files：**

- Create: `src/components/business/ModelPicker.vue`
- Create: `src/components/business/ModelPicker.spec.ts`
- Modify: `src/views/ChatView.vue`

**Interfaces：**

- Consumes: `listProviders()`、`getActiveProvider()`、`activateProvider()` 与现有 `ProviderConfig`。
- Produces: 无必填 props/无 emits 的共享模型选择组件；组件内部维护 `activeProvider`、Provider 列表、加载/切换/错误状态，并通过现有 API 激活全局 Provider。

- [ ] Step 1: 写失败测试：挂载时 active 请求未返回显示“加载中…”，返回已激活 Provider 后按钮直接显示模型名；不得先显示“未配置”。
- [ ] Step 2: 写失败测试：active 明确返回 `null` 才显示“未配置”；active 请求失败显示可重试状态；端点 unavailable 时组件按现有降级规则隐藏。
- [ ] Step 3: 写失败测试：Provider 列表在首次展开时才请求；切换 Provider 后按钮、当前徽标和菜单状态同步更新。
- [ ] Step 4: 写失败测试：挂载 active 请求与用户切换并发时，迟到的旧响应不得覆盖最新激活结果。
- [ ] Step 5: 运行 `npm exec -- vitest run src/components/business/ModelPicker.spec.ts`，预期新增测试失败。
- [ ] Step 6: 将 ChatView 内重复的 Provider 状态、API 调用、模板和 popover 样式迁移到 `ModelPicker.vue`；挂载时主动调用 `getActiveProvider()`，首次展开才调用 `listProviders()`；以递增 request version/activation version 丢弃迟到响应。
- [ ] Step 7: 保持 native button、可见 focus ring、Escape 关闭 popover、移动端至少 44×44 命中区和现有 Provider unavailable 降级。
- [ ] Step 8: 重跑组件 spec 与 `npm run typecheck`，预期通过。
- [ ] Step 9: 提交 `refactor(chat): share provider model picker`。

## Task 9：WorkspaceShell 接入模型选择并调整 composer 操作顺序

**Files：**

- Modify: `src/components/workspace/WorkspaceShell.vue`
- Modify: `src/components/workspace/WorkspaceShell.spec.ts`
- Modify: `e2e/model-picker.spec.ts`
- Modify: `e2e/workspace.spec.ts`
- Modify: `e2e/chat-mobile.spec.ts`

**Interfaces：**

- Consumes: Task 8 的 `ModelPicker`。
- Produces: WorkspaceShell 与 ChatView 使用同一全局 Provider；Workspace composer 的 leading actions 为“选择文件 → 引用”，composer actions 为“选择模型 → 停止/发送”。

- [ ] Step 1: 写失败测试：WorkspaceShell 渲染模型按钮；工作区挂载后无需打开菜单即可显示当前模型。
- [ ] Step 2: 写失败测试：Workspace composer DOM/可访问名称顺序为上传附件、引用文件、选择模型、发送/停止；引用文件选择器仍能打开并产生 `file_refs` chip。
- [ ] Step 3: 写失败测试：390×844 下工作区 composer 无页面级横向溢出，leading actions 与 model/send actions 均保持至少 44px 命中区。
- [ ] Step 4: 在 `WorkspaceShell` 的 composer-input 中增加 leading action group，将现有“引用”按钮移至 `AttachmentUploader` 旁；在原引用位置放置 `ModelPicker`，删除 WorkspaceShell 内重复 Provider 实现（如有）。
- [ ] Step 5: 重跑 WorkspaceShell spec、`e2e/model-picker.spec.ts`、Workspace 与移动端定向 E2E，预期通过。
- [ ] Step 6: 提交 `feat(workspace): add shared model picker to composer`。

## Task 10：双入口端到端验收

**Files：**

- Modify: `e2e/checkpoint-rollback.spec.ts`
- Modify: `src/mock/server.ts`
- Modify: `docs/plans/2026-08-30-checkpoint-rollback-correctness-frontend.progress.md`

**Interfaces：**

- Consumes: Tasks 1–9 和已批准的后端 v2 契约；后端契约未就绪时仅执行 Mock 验收。
- Produces: 普通会话与工作区会话的可复现验收证据。

- [ ] Step 1: E2E 验证打开弹窗时 Both 真实 checked，preview ready 后不切换 radio 即可成功确认。
- [ ] Step 2: 拦截三个 preview 并乱序返回，断言 UI 和 execute 始终使用最后选择的模式/request id。
- [ ] Step 3: 构造两轮对话；回滚第一条时第一条及以后全部消失、输入和附件回草稿、轨迹不再含目标 USER/assistant/tool 节点。
- [ ] Step 4: 在 WorkspaceShell 重复 Step 3，并断言 `file_refs` 恢复。
- [ ] Step 5: 覆盖 `code_only`：消息和输入框完全不变。
- [ ] Step 6: 覆盖运行中回滚：先 cancel 并确认后端终态；成功后无 cancelled/partial 气泡、无迟到 assistant，composer 可输入。cancel 失败时弹窗不出现。
- [ ] Step 7: 覆盖 Task 6 的回滚操作再次回滚：inverse operation 可继续来回切换；composer baseline 相同则清空，用户已编辑则保留并提示。
- [ ] Step 8: 运行 `npm run typecheck`、`npm run test:unit`、`npm run lint:check`、`npm run build`，再运行定向 Chromium E2E。
- [ ] Step 9: E2E 验证普通会话和 WorkspaceShell 首次打开时直接显示当前模型；切换 Provider 后两入口显示一致。
- [ ] Step 10: E2E 验证 Workspace composer 操作顺序、引用功能和 390×844 无横向溢出。
- [ ] Step 11: 使用 `review-test-simplify` 完成 Test/Review/Simplify gate；不得手工修改后端 `frontend_dist`，只在归属确认后由构建同步。
- [ ] Step 12: 后端 v2 就绪后执行真实 API/SSE 联调；否则在账本中明确记录 Mock-only 验收边界。
- [ ] Step 13: 提交 `test(checkpoint): verify deterministic rollback and draft restore`。

---

## 前端审批清单

- [x] 契约字段可由现有 composer、attachment 和 file-ref 类型无损消费。
- [x] 默认 Both、乱序 preview 和确认条件没有隐含的双请求路径。
- [x] 普通会话与 WorkspaceShell 使用同一裁剪/草稿转换语义，并同样防止切会话旧结果回写。
- [x] `code_only` 不触碰 composer 和消息历史。
- [x] `failed_partial` 只按权威 conversation action 应用，不按 status 猜测。
- [x] 首条消息回滚、附件失效且阻止发送、运行终态、generation 丢弃迟到 SSE 和 operation undo 草稿保护均有测试。
- [x] 首次进入普通会话和工作区时 active Provider 不误显示“未配置”，Workspace composer 操作顺序和移动端命中区均有测试。
- [x] 用户已审批前端计划；后端 v2 真实联调仍以后端 Agent 的审批/交付状态为准。

## 审批记录

`APPROVED_USER — 2026-08-30，审批人：用户。`

审批结论：用户批准前端修订计划，包含 `checkpoint-restore-v2` 前端消费、普通会话/WorkspaceShell 回滚闭环、共享 ModelPicker、首次 active provider 初始化修复、Workspace composer 操作顺序调整及 Mock 门禁。真实后端联调不替代后端 Agent 对其 v2 计划的审批与交付。
