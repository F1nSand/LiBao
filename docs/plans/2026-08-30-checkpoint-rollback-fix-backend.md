# Checkpoint 回滚异常修复——后端实施计划

**Goal:** 修复普通会话 checkpoint 身份不匹配和运行中用户消息缺少 checkpoint 锚点的问题，同时保证仅对话回滚不依赖文件工作区，并为前端工作区入口提供稳定、向后兼容的 SSE 契约。

**Architecture:** 新增唯一的 workspace identity 领域模块，由 checkpoint 创建端和恢复端共同调用；identity 仍绑定会话/工作区根目录，但对 Windows 路径做统一规范化，并只对白名单内的旧 `None:<root>` 普通会话 manifest 提供兼容。用户消息落库并提交后，首个 `message_start` 同时返回真实用户消息 ID 与 checkpoint ID，前端据此更新乐观消息。`conversation_only` 在路由和恢复服务中走纯会话分支，不解析工作区、不生成文件计划。

**Frontend contract:** 对应前端计划位于 `C:\Users\Admin1\Desktop\Agent\FrontEnd\docs\plans\2026-08-30-checkpoint-rollback-fix-frontend.md`；交接状态登记在 `C:\Users\Admin1\Desktop\Agent\FrontEnd\progress.md`。

## Global Constraints

- 本计划只修改后端源码、后端测试和后端契约文档，不修改 `FrontEnd/src` 或手工编辑 `frontend_dist`。
- 仅 `code_only`、`both` 校验 workspace identity 和构建文件 diff；`conversation_only` 不读取或写入任何工作区文件。
- 旧普通会话 manifest `None:<root>` 仅在 root 规范化后与当前会话临时目录完全一致时兼容；不得用前缀兼容绕过 root 校验。
- 空 root 的旧 identity 不允许执行代码恢复；仍允许 `conversation_only`。
- SSE 新字段必须可选，旧前端、Agent 试跑流和 resume/recovery 流保持兼容。
- preview 必须绑定创建它的 conversation；其他会话不得执行该 preview。
- 不改变 shell、脚本、数据库、MCP、记忆、知识库不纳入代码回滚的既有边界。
- 所有修复遵循测试先行；每个失败测试必须先观察到预期失败，再写最小实现。

---

## Cross-end Contract

普通聊天首帧保持现有事件类型：

```json
{
  "type": "message_start",
  "payload": {
    "message_id": "<assistant-message-uuid>",
    "agent_id": "<agent-uuid>",
    "conversation_id": "<conversation-uuid>",
    "task_id": "<task-uuid-or-null>",
    "user_message_id": "<persisted-user-message-uuid>",
    "checkpoint_id": "<code-checkpoint-uuid>"
  }
}
```

- `message_id` 继续表示本轮 assistant message ID，不改变语义。
- `user_message_id`、`checkpoint_id` 为新增可选字段；在普通 `/chat/stream` 成功持久化用户消息后必须同时存在。
- 写入 task event replay 的 `message_start` 使用同一个 payload，断线重放不得丢字段。
- confirmation resume 不重新发送 `message_start`；recovery 专用 `message_start` 可不带这两个字段。
- `checkpoint_id` 必须等于持久化 `Message.checkpoint_id`，且对应同 conversation 的 manifest。

---

## Task 1: 建立唯一 Workspace Identity 领域契约

**Files:**
- Create: `app/checkpoints/identity.py`
- Modify: `app/orchestration/chat_stream.py`
- Modify: `app/checkpoints/restore.py`
- Test: `tests/test_checkpoint_identity.py`
- Test: `tests/test_checkpoint_restore.py`

**Interfaces:**
- Produces: `build_workspace_identity(workspace_root: str, workspace_id: str | None) -> str`
- Produces: `workspace_identity_matches(stored_identity: str, workspace_root: str, workspace_id: str | None) -> bool`
- Consumes: `CodeCheckpoint.workspace_identity: str`

- [ ] Step 1: 新建 `tests/test_checkpoint_identity.py`，写 `test_build_session_identity_uses_session_scope_and_canonical_root`；输入 `workspace_id=None` 和含 `.` 的临时路径，断言结果前缀为 `session:` 且 root 等于 `Path.resolve(strict=False)` 后的规范值。
- [ ] Step 2: 写 `test_build_workspace_identity_keeps_uuid_scope`，断言真实 workspace UUID 作为 scope 且 root 规范化。
- [ ] Step 3: 写 `test_match_accepts_legacy_none_scope_only_for_same_session_root`，断言 `None:<同一root>` 对普通会话为真，但不同 root、真实 workspace、空 root 均为假。
- [ ] Step 4: 写 `test_match_tolerates_windows_case_and_separator_representation`；仅在 Windows 上断言大小写与分隔符差异经 `normcase/resolve` 后匹配。
- [ ] Step 5: 运行 `pytest tests/test_checkpoint_identity.py -q`，预期因模块不存在而 FAIL。
- [ ] Step 6: 在 `identity.py` 实现 `_canonical_root()`：`Path(root).expanduser().resolve(strict=False)` 后交给 `os.path.normcase`，最终统一为 POSIX 分隔符；空 root 抛 `ValueError`。
- [ ] Step 7: 实现 build/match；解析 stored identity 时只按第一个 `:` 分割 scope，保留 Windows 盘符；普通会话允许 scope `session` 或旧 `None`，真实 workspace 只允许 UUID 字符串精确相等。
- [ ] Step 8: 把 `chat_stream_events()` 的内联 identity 拼接替换为 `build_workspace_identity(workspace['root_path'], workspace.get('id'))`。
- [ ] Step 9: 把 `CheckpointRestoreService._identity()` 和字符串精确比较替换为共享 helper；旧 `None:<same-root>` 可立即恢复，无需重写 manifest。
- [ ] Step 10: 运行 identity 与 restore 定向测试，预期 PASS。
- [ ] Step 11: Commit: `fix(checkpoint): canonicalize workspace identity`

---

## Task 2: 切断 Conversation-only 对文件工作区的依赖

**Files:**
- Modify: `app/api/routers/checkpoints.py`
- Modify: `app/checkpoints/restore.py`
- Test: `tests/test_checkpoint_restore.py`
- Create: `tests/test_checkpoint_api.py`

**Interfaces:**
- Changes: `CheckpointRestoreService.preview_checkpoint(..., workspace_root: str | None, workspace_id: str | None = None) -> dict[str, Any]`
- Preserves: `POST /conversations/{id}/restore-previews` request/response JSON
- Produces: `conversation_only` preview with `files=[]` and no workspace resolution

- [ ] Step 1: 写 `test_conversation_only_preview_ignores_workspace_identity_mismatch`，构造错误/旧 identity 的 checkpoint，传 `workspace_root=None`，断言 preview 成功且 `files == []`。
- [ ] Step 2: 写 `test_conversation_only_preview_succeeds_when_workspace_is_missing` 的 API 测试：工作区解析函数若被调用就抛异常，断言 endpoint 仍返回成功。
- [ ] Step 3: 写 `test_code_modes_still_reject_workspace_identity_mismatch`，分别覆盖 `code_only`、`both` 返回 40932。
- [ ] Step 4: 运行三项测试，预期现有实现因无条件 identity 校验和 `_file_plan` 调用而 FAIL。
- [ ] Step 5: 调整 router：checkpoint target 且 mode 为 `conversation_only` 时不调用 `_workspace_context()`，传 `workspace_root=None`；其他模式及 operation-before 保持精确工作区解析。
- [ ] Step 6: 调整 `preview_checkpoint()`：先校验 checkpoint 存在；仅在 `mode in {'code_only','both'}` 时要求非空 root、校验 identity、调用 `_file_plan`；纯会话模式设置 `files=[]`、`target_refs={}`。
- [ ] Step 7: 调整 `execute_preview()`：纯会话 preview 不构造 `Path(None)`，不重新计算文件计划；只更新 active message/cursor 和 operation 记录。
- [ ] Step 8: 运行 restore/API 定向测试，预期 PASS。
- [ ] Step 9: Commit: `fix(checkpoint): isolate conversation-only restores`

---

## Task 3: 固化会话 Workspace 绑定，防止后续 Identity 漂移

**Files:**
- Modify: `app/api/routers/chat.py`
- Modify: `app/core/errors.py`
- Create: `tests/test_chat_workspace_binding.py`

**Interfaces:**
- Preserves: 新建会话时 `req.workspace_id` 写入 `Conversation.workspace_id`
- Adds: `ERR_CONVERSATION_WORKSPACE_CONFLICT = 40909`
- Adds: 已有 conversation 的 `req.workspace_id` 与持久化绑定不一致时返回 code `40909`

- [ ] Step 1: 写 `test_existing_session_conversation_rejects_workspace_override`：普通 conversation 携带真实 `workspace_id` 再发消息时，断言请求被拒绝，conversation 仍为 session。
- [ ] Step 2: 写 `test_existing_workspace_conversation_rejects_different_workspace`，断言不能切到另一个 workspace。
- [ ] Step 3: 写 `test_new_workspace_conversation_persists_workspace_id`，断言首次创建后 checkpoint 创建端和 restore 解析端读取同一 workspace。
- [ ] Step 4: 运行测试，预期前两项因当前 `conversation.workspace_id or req.workspace_id` 逻辑而 FAIL。
- [ ] Step 5: 在 `app/core/errors.py` 新增 `ERR_CONVERSATION_WORKSPACE_CONFLICT = 40909`；在 chat router 中区分新建/已有 conversation，已有 conversation 只以持久化 `conversation.workspace_id` 为权威，请求显式 workspace 与之不一致时抛 `AppError(40909, '会话绑定的工作区与请求不一致')`，新会话沿用 create 时持久化绑定。
- [ ] Step 6: 将后续 `ws_id` 设为 `conversation.workspace_id`，不得用请求值临时覆盖。
- [ ] Step 7: 运行 chat router 定向测试，预期 PASS。
- [ ] Step 8: Commit: `fix(chat): keep conversation workspace binding stable`

---

## Task 4: 在首帧返回真实用户消息 Checkpoint 锚点

**Files:**
- Modify: `app/orchestration/chat_stream.py`
- Modify: `docs/03-api-contracts.md`
- Test: `tests/test_chat_stream.py`
- Test: `tests/test_interrupt_stream.py`

**Interfaces:**
- Adds optional fields: `message_start.payload.user_message_id: string`
- Adds optional fields: `message_start.payload.checkpoint_id: string`
- Preserves: `message_start.payload.message_id` remains assistant message ID

- [ ] Step 1: 在 `tests/test_chat_stream.py` 写 `test_message_start_exposes_persisted_user_checkpoint_anchor`；消费第一帧后读取 MessageRepository 和 manifest，断言两个新增字段分别等于真实 user message ID 与 `Message.checkpoint_id`。
- [ ] Step 2: 扩展 task event 测试，断言 `push_event` 保存的 `message_start` payload 与 SSE payload 的两个锚点字段一致。
- [ ] Step 3: 在中断测试中断言 `message_start` 先于 interrupt 到达，且锚点 checkpoint 状态为 open/interrupted、可供后续恢复。
- [ ] Step 4: 写兼容测试：resume/recovery 的既有 `message_start` 无新增字段时事件序列和前端重置约束不变。
- [ ] Step 5: 运行定向测试，预期首三项因字段缺失而 FAIL。
- [ ] Step 6: 在用户消息 commit 成功后构造首帧时加入 `user_message_id=str(user_msg.id)`、`checkpoint_id=str(checkpoint.id)`；同一 payload 同时传给 `push_event` 与 `emit`。
- [ ] Step 7: 更新 SSE 契约文档，明确新增字段可选以及 `message_id` 的既有语义。
- [ ] Step 8: 运行 chat/interrupt/task-event 定向测试，预期 PASS。
- [ ] Step 9: Commit: `feat(checkpoint): expose live user message anchor`

---

## Task 5: 绑定 Restore Preview 所属会话

**Files:**
- Modify: `app/checkpoints/restore.py`
- Test: `tests/test_checkpoint_restore.py`
- Test: `tests/test_checkpoint_api.py`

**Interfaces:**
- Consumes: preview record field `conversation_id`
- Produces: cross-conversation preview execution rejection with deterministic 409 application error

- [ ] Step 1: 写 `test_preview_cannot_be_executed_by_another_conversation`：conversation A 创建 preview，conversation B 使用同一 preview ID，断言 409，A/B 的文件和 cursor 均不变。
- [ ] Step 2: 写 operation-before 等价测试，确保可逆 operation preview 同样绑定 conversation。
- [ ] Step 3: 运行测试，预期当前实现至少一项 FAIL。
- [ ] Step 4: 在 revision、task、workspace/file 操作之前验证 `record['conversation_id'] == str(conversation.id)`；不一致立即拒绝且不消费 preview。
- [ ] Step 5: 运行 restore/API 定向测试，预期 PASS。
- [ ] Step 6: Commit: `fix(checkpoint): bind restore previews to conversation`

---

## Task 6: 后端回归与交付门禁

**Files:**
- Modify: `progress-checkpoint-rollback-fix-backend.md` only when execution is approved
- No production code changes unless a failing gate reveals a regression directly caused by Tasks 1–5

- [ ] Step 1: 运行 `pytest tests/test_checkpoint_identity.py tests/test_checkpoint_restore.py tests/test_chat_stream.py tests/test_interrupt_stream.py -q`。
- [ ] Step 2: 运行 checkpoint API 与 chat router 对应测试文件。
- [ ] Step 3: 运行 `ruff check app/checkpoints app/api/routers/checkpoints.py app/api/routers/chat.py app/orchestration/chat_stream.py tests/test_checkpoint_identity.py tests/test_checkpoint_restore.py`。
- [ ] Step 4: 运行 `python -m compileall -q app`。
- [ ] Step 5: 运行后端全量 `pytest -q`，记录 passed/skipped/warnings。
- [ ] Step 6: 检查 `git diff --check`；确认未混入 `frontend_dist` 或用户已有工作区改动。
- [ ] Step 7: 在 `FrontEnd/progress.md` 将后端交接项从 `[open]` 更新为 `[ready]`，填写实际字段、测试结果和后端 commit；不得标记前端任务 done。
- [ ] Step 8: Commit: `test(checkpoint): verify rollback contract fixes`

---

## Acceptance Criteria

- 普通会话现有 `None:<same-root>` checkpoint 与新建 `session:<canonical-root>` checkpoint 均可生成 preview。
- 不同普通会话目录、不同真实 workspace 或空 root 仍返回 40932，不能降低隔离强度。
- `conversation_only` 在临时目录已清理或 workspace 不可用时仍可预览和执行，且文件保持不变。
- 新用户消息持久化后第一帧即返回 `user_message_id`、`checkpoint_id`；刷新前前端已有足够信息显示回滚入口。
- WorkspaceShell 可使用同一 REST/SSE 契约完成回滚，不需要后端新增 workspace 专用 endpoint。
- 其他会话无法执行偷取到的 preview ID。
- 后端定向和全量测试、Ruff、compileall 全部通过。
