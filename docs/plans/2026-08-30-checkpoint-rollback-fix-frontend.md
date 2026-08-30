# Checkpoint 回滚异常修复——前端实施计划

**Goal:** 让普通会话与工作区会话都能即时显示并执行消息级回滚，将占位过大的文字按钮替换为符合现有设计系统的图标操作栏，并增加可靠的消息复制能力。

**Architecture:** `useChatStream` 消费后端 `message_start` 的用户消息锚点，通过显式回调让 Chat store 与 WorkspaceShell 分别幂等更新自己的乐观消息；不通过刷新列表补锚点。`MessageBubble` 只负责渲染和复制，回滚事件继续经 `MessageList` 上抛；`ChatView` 与 `WorkspaceShell` 各自承接停止任务、打开共享 `CheckpointRestoreDialog`、完成后刷新数据。操作栏使用现有 Element Plus 图标和设计 token，鼠标 hover、键盘 `:focus-visible`、触屏常显三套输入语义一致。

**Backend dependency:** 后端计划位于 `C:\Users\Admin1\Desktop\Agent\Agent\docs\plans\2026-08-30-checkpoint-rollback-fix-backend.md`。执行本计划前，后端 `message_start.payload.user_message_id/checkpoint_id` 契约必须达到 `FrontEnd/progress.md` 的 `[ready]` 状态。

## Global Constraints

- 不修改后端源码，不手工编辑 `Agent/frontend_dist`；前端构建完成后按仓库既有流程同步产物。
- 保持 `message_start.payload.message_id` 为 assistant message ID；只消费新增可选字段，不改变旧字段语义。
- 对旧后端缺少锚点字段时保持现状，不抛异常；刷新后仍可从消息列表获得 checkpoint。
- 同一 task event replay 重复送达时不得追加重复用户消息或覆盖其他 conversation 的乐观消息。
- 回滚只在持久化用户消息且有 checkpoint 时显示；复制只在非流式、正文非空的持久化消息上显示。
- 用户消息操作顺序固定为：左侧回滚、右侧复制；assistant 持久化文本消息只显示复制。
- 空正文纯附件/纯文件引用消息不显示复制，但有 checkpoint 时仍显示回滚。
- 图标按钮必须有 `title`、`aria-label`、可见 focus ring；不得只靠 hover 提供功能。
- 点击回滚时若任务仍执行，沿用“先 stop，确认已停止后再打开 preview”的既有语义。
- 所有改动测试先行；执行前端全量 typecheck、Vitest、lint、build，并覆盖普通会话和 WorkspaceShell 两条路径。

---

## Backend Contract Consumed by Frontend

```ts
export interface MessageStartPayload {
  message_id: string
  agent_id?: string
  conversation_id: string
  task_id?: string
  user_message_id?: string
  checkpoint_id?: string
}

export interface CheckpointAnchor {
  conversationId: string
  userMessageId: string
  checkpointId: string
}
```

- 仅当 `conversation_id/user_message_id/checkpoint_id` 都为非空字符串时触发 anchor 回调。
- task event replay 可重复交付相同 anchor；消费者必须幂等。
- recovery/旧后端允许两个新增字段缺省。

---

## Task 1: 扩展 SSE 类型与 Checkpoint Anchor 回调

**Files:**
- Modify: `src/types/sse.ts`
- Modify: `src/composables/useChatStream.ts`
- Test: `src/composables/useChatStream.spec.ts`

**Interfaces:**
- Adds: `UseChatStreamOptions.onCheckpointAnchor?: (anchor: CheckpointAnchor) => void`
- Consumes: optional `MessageStartPayload.user_message_id/checkpoint_id`

- [ ] Step 1: 在 `useChatStream.spec.ts` 写测试：首个 `message_start` 带完整锚点时回调一次，字段映射准确。
- [ ] Step 2: 写 replay 幂等边界测试：相同 task event 重放时状态机可再次调用回调，但下游 reconcile 不产生重复消息；本层不得改变 assistant `messageId`。
- [ ] Step 3: 写兼容测试：缺少任一新增字段时不调用回调，旧 `message_start` 行为不变。
- [ ] Step 4: 运行定向测试，预期新增回调不存在而 FAIL。
- [ ] Step 5: 扩展 `MessageStartPayload` 与 options/return 相关类型；在 `message_start` case 更新现有状态后，校验三个字段并调用 `onCheckpointAnchor`。
- [ ] Step 6: 运行 `useChatStream.spec.ts`，预期 PASS。
- [ ] Step 7: Commit: `feat(checkpoint): consume live user anchor`

---

## Task 2: 幂等回填普通会话乐观用户消息

**Files:**
- Modify: `src/stores/chat.ts`
- Modify: `src/views/ChatView.vue`
- Test: `src/stores/chat.spec.ts`
- Test: `src/composables/useChatStream.spec.ts`

**Interfaces:**
- Adds: `chat.reconcileCheckpointAnchor(anchor: CheckpointAnchor): boolean`
- Consumes: `UseChatStreamOptions.onCheckpointAnchor`

- [ ] Step 1: 写 store 测试：当前 conversation 最后一条 `local_*` user message 被更新为服务端 ID 和 checkpoint ID，正文/附件/文件引用保持不变。
- [ ] Step 2: 写幂等测试：同一 anchor 调用两次，消息数量不变，第二次仍返回成功或稳定 no-op。
- [ ] Step 3: 写隔离测试：anchor.conversationId 与 currentId 不一致、没有 local user、已有不同 checkpoint 时均不得修改列表。
- [ ] Step 4: 运行测试，预期 method 不存在而 FAIL。
- [ ] Step 5: 在 store 从数组尾部查找 `role==='user' && id.startsWith('local_') && !checkpoint_id` 的唯一候选；替换 `id/checkpoint_id`，不追加新消息。
- [ ] Step 6: 在 ChatView 创建 `useChatStream` 时传 `onCheckpointAnchor: chat.reconcileCheckpointAnchor`；切换会话后的后台 anchor 由 conversation guard 忽略，回切时服务端 loadMessages 收敛。
- [ ] Step 7: 运行 store/chat 定向测试，预期 PASS。
- [ ] Step 8: Commit: `fix(chat): reconcile optimistic checkpoint anchors`

---

## Task 3: 为 WorkspaceShell 接通同一回滚流程

**Files:**
- Modify: `src/components/workspace/WorkspaceShell.vue`
- Test: `src/components/workspace/WorkspaceShell.spec.ts`

**Interfaces:**
- Consumes: `CheckpointAnchor`
- Consumes: `CheckpointRestoreDialog`
- Consumes: `MessageList` event `rollback(message: Message)`

- [ ] Step 1: 写 WorkspaceShell 测试：`MessageList` 发出 rollback 后，组件保存目标 message 并打开 `CheckpointRestoreDialog`。
- [ ] Step 2: 写运行中测试：触发 rollback 时先调用 `stream.stop()`；仍处于 streaming 时显示 warning 且不打开 dialog，停止成功才打开。
- [ ] Step 3: 写完成测试：dialog 发出 completed 后关闭、重新加载当前 messages 和 workspace conversations，旧请求版本不能覆盖新状态。
- [ ] Step 4: 写 anchor 回填测试：当前工作区 conversation 最后一条 local user 被更新为服务端 ID/checkpoint；其他 conversation 的 anchor 被忽略；replay 不增加数组长度。
- [ ] Step 5: 运行 WorkspaceShell 定向测试，预期因未接线而 FAIL。
- [ ] Step 6: 导入 `CheckpointRestoreDialog`；新增 `restoreVisible`、`restoreMessage`、`onRollback`、`onRestoreCompleted` 和局部 `reconcileCheckpointAnchor`。
- [ ] Step 7: 在 `useChatStream` options 中接入局部 anchor 回填；在 `MessageList` 增加 `@rollback="onRollback"`；在同一层挂载共享 dialog，props 与 ChatView 保持一致。
- [ ] Step 8: 对 conversation/workspace 切换清理 restore 状态，防旧 dialog 指向新会话。
- [ ] Step 9: 运行 WorkspaceShell 定向测试，预期 PASS。
- [ ] Step 10: Commit: `fix(workspace): wire checkpoint restore flow`

---

## Task 4: 将文字回滚按钮改为复制/回滚图标操作栏

**Files:**
- Modify: `src/components/business/MessageBubble.vue`
- Modify: `src/components/business/MessageBubble.spec.ts`

**Interfaces:**
- Emits: existing `rollback(message: Message)` unchanged
- Internal: `copyMessage(): Promise<void>` uses `navigator.clipboard.writeText(message.content)`
- Uses: Element Plus `RefreshLeft`, `CopyDocument`, `ElMessage`

- [ ] Step 1: 写渲染测试：带 checkpoint 的 user message 只出现两个 icon buttons，DOM 顺序为 rollback 后 copy，不包含可见文字“回滚到此状态”。
- [ ] Step 2: 写 assistant 测试：持久化非空文本只显示 copy，不显示 rollback；stream message 不显示 copy。
- [ ] Step 3: 写空正文测试：纯附件 user 不显示 copy，有 checkpoint 时仍显示 rollback。
- [ ] Step 4: 写复制成功测试：stub `navigator.clipboard.writeText`，点击 copy 后断言传入完整原始正文，并显示成功反馈。
- [ ] Step 5: 写复制失败测试：clipboard reject 时显示错误反馈，组件不抛出未处理 promise。
- [ ] Step 6: 写无障碍测试：两个按钮分别具有 `aria-label='回滚到此状态'`、`aria-label='复制消息'` 和对应 title。
- [ ] Step 7: 运行 MessageBubble 测试，预期现有文字按钮和缺少复制功能导致 FAIL。
- [ ] Step 8: 用 `.message-actions` 容器替换 `.rollback-trigger`；user 的回滚按钮在前、复制在后；assistant 文本气泡下只渲染复制。
- [ ] Step 9: 图标按钮使用现有 token，桌面可点击区域固定 30×30px、图标 15px、透明背景，hover/focus 状态与页面现有次级 icon button 一致；操作栏紧贴对应气泡右下角，不渲染可见文字。
- [ ] Step 10: 运行 MessageBubble 定向测试，预期 PASS。
- [ ] Step 11: Commit: `feat(chat): add compact message action icons`

---

## Task 5: 修复 Mouseleave 残留并保留键盘/触屏可达性

**Files:**
- Modify: `src/components/business/MessageBubble.vue`
- Test: `src/components/business/MessageBubble.spec.ts`
- Create: `e2e/checkpoint-rollback.spec.ts`

**Interfaces:**
- CSS behavior: mouse hover, keyboard focus-visible, touch always-visible

- [ ] Step 1: 组件测试断言样式/类不再依赖 `.msg.user:focus-within .rollback-trigger`，新操作栏具有稳定 class 供 E2E 查询。
- [ ] Step 2: Playwright 测试：hover user bubble 显示 actions，点击复制或打开/关闭回滚弹窗后把鼠标移出，actions 立即不可见。
- [ ] Step 3: Playwright 测试：Tab 聚焦隐藏操作栏中的按钮时操作栏可见，focus ring 存在；移走键盘焦点后隐藏。
- [ ] Step 4: Playwright mobile/touch 项目断言 actions 常显；`@media (hover: none)` 下透明触控区域固定至少 44×44px，可见图标保持 16px。
- [ ] Step 5: 运行 E2E，预期现有 `:focus-within` 导致 mouseleave 用例 FAIL。
- [ ] Step 6: CSS 改为 `.msg:hover .message-actions` 和 `.message-actions:has(.message-action:focus-visible)`；删除父消息容器的 `:focus-within` 显示规则。
- [ ] Step 7: 增加 `@media (hover: none)` 常显规则和 `prefers-reduced-motion` 降级；隐藏态禁止 pointer interaction，可聚焦按钮获得 focus-visible 后恢复显示。
- [ ] Step 8: 运行组件/E2E 定向测试，预期 PASS。
- [ ] Step 9: Commit: `fix(chat): hide pointer-focused actions on mouseleave`

---

## Task 6: 同步 Mock 契约与双入口 E2E

**Files:**
- Modify: `src/mock/server.ts`
- Modify: `src/types/sse.ts`
- Modify: `e2e/checkpoint-rollback.spec.ts`
- Modify: existing mock/server specs

- [ ] Step 1: mock chat `message_start` 返回真实 mock user message ID 和 checkpoint ID，并将同一字段写入 mock task event log。
- [ ] Step 2: mock 断线 replay 重发同一 anchor，验证普通 chat 与 WorkspaceShell 均不产生重复 user message。
- [ ] Step 3: E2E 普通会话：发送后收到首帧即显示回滚图标，无需切换会话或刷新；点击能打开三模式 preview。
- [ ] Step 4: E2E 工作区：新建/选择 workspace conversation，点击回滚图标能打开 dialog，执行成功后消息刷新。
- [ ] Step 5: E2E 操作栏：用户气泡顺序为 rollback→copy，assistant 为 copy only；复制内容等于原消息文本。
- [ ] Step 6: 运行 mock/server、stream、bubble、WorkspaceShell 定向测试和 checkpoint E2E，预期 PASS。
- [ ] Step 7: Commit: `test(checkpoint): cover live anchors and workspace rollback`

---

## Task 7: 前端交付门禁与构建同步

**Files:**
- Modify: `progress.md`
- Generate: `dist/**`
- Sync after approval: `C:\Users\Admin1\Desktop\Agent\Agent\frontend_dist/**`

- [ ] Step 1: 运行 `npm run typecheck`。
- [ ] Step 2: 运行 `npm run test:unit`；若仅出现既有 `useNotifications` 5 秒并发超时，单独运行该 spec，并用 `npx vitest run --maxWorkers=1 --minWorkers=1` 完成全量复核，两次结果都写入交接回执。
- [ ] Step 3: 运行 `npm run lint:check`，区分新增错误与既有 warning。
- [ ] Step 4: 运行 `npm run build`。
- [ ] Step 5: 运行 checkpoint 定向 Chromium E2E，覆盖普通会话、workspace、首帧锚点、mouseleave、键盘、复制。
- [ ] Step 6: 更新 `progress.md`：记录前端 commit、测试数、E2E 数及后端契约版本，把前端事项标记 `[done]`。
- [ ] Step 7: 在确认后端 `frontend_dist` 的既有 dirty changes 归属后再同步构建产物；不得覆盖或提交其他任务的未提交产物。
- [ ] Step 8: Commit: `chore(frontend): sync checkpoint rollback build`

---

## Acceptance Criteria

- 普通 `/chat` 发送后不刷新即可出现回滚图标。
- WorkspaceShell 点击回滚必定打开共享 preview；运行中先停止，失败给出明确提示。
- 鼠标移出消息后图标栏消失，不因点击后焦点残留；Tab 键和触屏仍可访问。
- 用户气泡右下角仅显示紧凑图标，顺序为回滚在左、复制在右；无可见长文案。
- assistant 持久化文本可复制，流式未封口内容不可复制。
- replay、切换 conversation/workspace 不重复消息、不串 checkpoint。
- 前端 typecheck、全量 Vitest、lint、build、定向 E2E 全部通过。
