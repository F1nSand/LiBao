# 会话任务刷新重连与启动恢复实施计划

**状态：** `AWAITING_USER_APPROVAL`

**Goal：** 实现浏览器刷新后的会话 Task 自动发现、业务事件 cold replay/live-tail，以及后端重启后 orphan Task 的安全对账和精确 checkpoint 人工恢复。

**Architecture：** Task 显式持久化 `conversation_id` 与经后端验证的 `recovery_graph_checkpoint_id`；后端提供 owner-scoped active-task 摘要并用 conversation lock 保证单会话单活。前端用 URL 恢复会话选择，再从 `after_seq=0` 重建业务轨迹。服务启动只把遗留任务收敛为 done、recoverable failed 或 non-recoverable failed，绝不自动重跑工具。

**设计依据：** `docs/superpowers/specs/2026-08-30-conversation-task-reconnect-design.md`

**Execution：** 用户批准后使用 `executor-debugger` 按 Task 顺序执行并维护独立 progress ledger；最终提交前使用 `review-test-simplify` 完成 Test/Review/Simplify gate。

## Global Constraints

- 保持本地单机 FileStore + `asyncio.Task` 架构；不引入 Redis、外部队列或多实例 lease。
- 不增加 `interrupted` Task status；重启中断用 `failed + error.kind=process_restart` 表达。
- 不自动恢复进程重启任务；只有用户明确点击“从断点继续”才执行。
- 只有后端验证过的精确 `recovery_graph_checkpoint_id` 才能令 `error.recoverable=true`。
- 禁止根据 thread 时间顺序猜 graph cursor；聊天 Task 必须按自身 code checkpoint anchor 解析 output。
- token/thinking 不持久化、不补发；业务边界事件从 `task_seq=1` 起回放。
- shell、MCP、数据库和远程 API 副作用不保证 exactly-once；恢复确认 UI 必须提示可能重复。
- URL 只保存 conversation ID，不保存或信任 task ID；Task ID 始终由 owner-scoped 后端查询返回。
- 旧 `tasks.json` 无新增字段时必须可读；旧任务关联会话时回退 `input/pending_confirm.conversation_id`。
- 同会话 `pending/running/waiting_confirm` Task 最多一个；服务端约束是最终防线。
- 前后端分别在各自仓库提交；不得把 `FrontEnd` 源文件复制进后端仓库。

---

## Task 1：冻结 Task 数据结构、错误码和安全摘要契约

**Backend Files：**

- Modify: `app/storage/models/task.py:10-26`
- Modify: `app/core/errors.py:72-82`
- Modify: `app/services/serializers.py:278-296`
- Modify: `docs/03-api-contracts.md`
- Test: `tests/test_file_store.py`
- Test: `tests/test_tasks_api.py`

**Interfaces：**

- Produces: `Task.conversation_id: uuid.UUID | None = None`
- Produces: `Task.recovery_graph_checkpoint_id: str | None = None`
- Produces: `ERR_TASK_PROCESS_INTERRUPTED = 60009`
- Produces: `serialize_active_task(task: Task) -> dict[str, Any]`，只返回 `id/status/last_event_seq/started_at/updated_at/pending_confirm/error`。

- [ ] Step 1: 在 `tests/test_file_store.py` 写失败测试 `test_legacy_task_without_conversation_or_recovery_cursor_loads_with_none_defaults`，用缺少两个新字段的旧 JSON row 重载 FileStore，断言字段为 `None`。
- [ ] Step 2: 在 `tests/test_tasks_api.py` 写失败测试 `test_active_task_summary_does_not_expose_task_input`，断言摘要包含事件水位与恢复状态，但不含 message、附件、file_refs 或完整 input。
- [ ] Step 3: 运行上述两个测试，确认因字段/serializer 缺失而 FAIL。
- [ ] Step 4: 增加 Task 字段、60009 错误码和安全摘要 serializer；保持现有 `serialize_task` 向后兼容。
- [ ] Step 5: 更新 `docs/03-api-contracts.md`，写明 active/recoverable/null 三态、60009 和 `after_seq=0` cold replay 规则。
- [ ] Step 6: 重跑测试与 `ruff check app/storage/models/task.py app/core/errors.py app/services/serializers.py tests/test_file_store.py tests/test_tasks_api.py`，预期 PASS。
- [ ] Step 7: 提交 `feat(task): persist conversation and recovery cursors`。

## Task 2：会话当前 Task 查询与单会话单活提交

**Backend Files：**

- Modify: `app/storage/repositories/task.py:47-86`
- Modify: `app/services/task.py:31-81`
- Modify: `app/api/routers/conversations.py`
- Modify: `app/api/routers/chat.py:115-147`
- Test: `tests/test_tasks_api.py`
- Test: `tests/test_chat_stream.py`

**Interfaces：**

- Consumes: Task 1 的显式 `conversation_id` 和安全摘要。
- Produces: `TaskRepository.get_current_for_conversation(user_id, conversation_id) -> tuple[Task | None, Literal["active", "recoverable"] | None]`。
- Produces: `TaskRepository.get_inflight_for_conversation(user_id, conversation_id) -> Task | None`，只匹配 `pending/running/waiting_confirm`。
- Produces: `TaskService.submit_for_conversation(db, user, agent_id, conversation_id, input) -> Task`，在 conversation lock 内完成查重和 commit。
- Produces: `GET /api/v1/conversations/{conversation_id}/active-task` → `{conversation_id, relation, task}`。

- [ ] Step 1: 写 repository 失败测试：新字段关联、旧 `input.conversation_id` 回退、`pending/running/waiting_confirm` active、`failed+recoverable` fallback、done/cancelled/nonrecoverable 排除，并断言最新 Task 优先。
- [ ] Step 2: 写 API 失败测试 `test_get_conversation_active_task_owner_scoped`、`test_get_conversation_active_task_returns_active_recoverable_and_null`，覆盖越权 40401 与三态响应。
- [ ] Step 3: 写并发失败测试 `test_submit_for_conversation_allows_only_one_inflight_task`，用两个并发协程提交同一 conversation，断言一个成功、一个 `ERR_TASK_RUNNING=40901`，存储中只有一个非终态 Task。
- [ ] Step 4: 写 chat 路由失败测试：刷新后旧 Task 仍 running 时再次 `POST /chat/stream` 返回 40901，graph 不启动、用户消息/checkpoint 不新增；不同 conversation 可并发创建。
- [ ] Step 5: 实现兼容查询、conversation lock、submit service 和 endpoint；chat 路由移除 waiting-only 创建路径，统一走 `submit_for_conversation`。
- [ ] Step 6: 跑 `tests/test_tasks_api.py tests/test_chat_stream.py tests/test_interrupt_stream.py tests/test_cancel_inflight.py`，确认 active 查询、interrupt/resume、cancel 无回归。
- [ ] Step 7: 跑 Ruff/compileall 并提交 `feat(task): expose active conversation runs`。

## Task 3：启动时识别 orphan Task 并保存精确 graph cursor

**Backend Files：**

- Create: `app/services/task_recovery.py`
- Modify: `app/storage/repositories/task.py`
- Modify: `app/api/main.py:46-87`
- Modify: `app/storage/repositories/message.py`
- Test: `tests/test_task_restart_recovery.py`
- Test: `tests/test_task_events.py`

**Interfaces：**

- Consumes: Task 1 的 `recovery_graph_checkpoint_id` 与 60009；Task 2 的 conversation 兼容关联。
- Produces: `reconcile_orphaned_tasks(checkpointer) -> RestartReconcileStats`。
- Produces: `RestartReconcileStats` 字段 `completed/recoverable/nonrecoverable/unchanged`。
- Produces: 每个实际迁移的 Task 一条单调 `error` 或 `done` task event；重复调用不追加第二条。

- [ ] Step 1: 写失败测试 `test_restart_reconcile_pending_without_checkpoint_is_nonrecoverable`：pending → failed，`kind=process_restart/recoverable=false`，error event 恰好一条。
- [ ] Step 2: 写失败测试 `test_restart_reconcile_chat_running_uses_its_code_anchor_output`：同 conversation 构造多个 run/失败 checkpoint；只允许按该 Task `input.checkpoint_id` 的 `get_run_bounds().output_id` 显式验证并保存，不能选择 thread 最新失败节点。
- [ ] Step 3: 写失败测试 `test_restart_reconcile_chat_without_checkpoint_anchor_is_not_recoverable`：running 但尚未回填 code checkpoint id 时不得猜 cursor。
- [ ] Step 4: 写失败测试 `test_restart_reconcile_background_task_persists_verified_latest_cursor`：独占 `thread_id=task.id` 的后台 Task 读取 latest tuple、提取 checkpoint ID、再显式读取验证后才设 recoverable。
- [ ] Step 5: 写失败测试 `test_restart_reconcile_preserves_waiting_confirm_and_terminal_tasks`，覆盖 waiting_confirm/done/cancelled/failed 均不变。
- [ ] Step 6: 写失败测试 `test_restart_reconcile_repairs_running_after_final_message_commit_to_done`：从 task event 的 message_start 取得 assistant message ID；Message 已存在时补 Task done/done event，不生成第二条 Message。
- [ ] Step 7: 写失败测试 `test_restart_reconcile_is_idempotent`：连续调用两次，第二次 stats 全 unchanged，task event 数量和 last_event_seq 不变。
- [ ] Step 8: 实现对账服务；所有 Task 先由存储状态和显式 tuple 证明，再更新状态/游标；不调用 spawn_run/spawn_recovery。
- [ ] Step 9: 在 lifespan 的 graph/checkpoint 初始化完成后、`yield` 前调用对账服务并记录统计日志；失败只记录异常并保持应用可启动，但不得把未验证 Task 标为 recoverable。
- [ ] Step 10: 跑 `tests/test_task_restart_recovery.py tests/test_task_events.py tests/test_json_file_saver.py tests/test_checkpoint_restore.py` 与 Ruff，预期 PASS。
- [ ] Step 11: 提交 `feat(task): reconcile orphaned runs on startup`。

## Task 4：process_restart 恢复必须消费 Task 的精确游标

**Backend Files：**

- Modify: `app/orchestration/stream_core.py:321-327`
- Modify: `app/orchestration/task_run.py:57-98,323-355`
- Modify: `app/orchestration/chat_stream.py:602-750,933-953`
- Modify: `app/api/routers/tasks.py:184-213`
- Modify: `app/services/task.py:216-242`
- Test: `tests/test_task_restart_recovery.py`
- Test: `tests/test_llm_transport_retry.py`
- Test: `tests/test_interrupt_stream.py`

**Interfaces：**

- Consumes: Task 3 持久化的 `Task.recovery_graph_checkpoint_id`。
- Produces: `_run_graph_common(..., graph_checkpoint_id: str | None = None)`。
- Produces: `recover_task_graph(..., graph_checkpoint_id: str | None = None)`。
- Produces: `retry_stream_events`/`resume_stream_events` 在 `error.kind=process_restart` 时把 cursor 作为 `_graph_config(graph_parent_checkpoint_id=...)` 传入。

- [ ] Step 1: 写失败测试 `test_explicit_recovery_cursor_wins_over_latest_failed_checkpoint`：同一 thread 放置目标 restart cursor 和另一轮更新的 `__error__`；恢复必须从目标 cursor 开始，resolver 不得覆盖。
- [ ] Step 2: 写失败测试 `test_restart_recover_without_persisted_cursor_is_rejected`：即使客户端请求 recover，Task 无 cursor 时仍返回 40902，不进入 graph。
- [ ] Step 3: 写失败测试 `test_llm_transport_recovery_still_uses_failed_checkpoint_resolver`，确保旧 transport recovery 无显式 cursor 时行为不变。
- [ ] Step 4: 修改 stream core：仅 `initial is None` 且 configurable 没有显式 `checkpoint_id` 时调用 `aget_failed_config`。
- [ ] Step 5: 将精确 cursor 贯穿 chat/background 两条 recovery 路径；只在 `task.error.kind == "process_restart"` 时消费该字段，恢复后的新错误不能继续误用旧 cursor。
- [ ] Step 6: 验证 idempotency key、重复 recover、三次上限、chat 消息不重复、已完成工具轮不重复落库。
- [ ] Step 7: 跑 restart/transport/interrupt/chat/task 定向测试与 Ruff，提交 `fix(task): recover from verified restart cursor`。

## Task 5：前端 active-task API、URL 会话恢复和消息幂等

**Frontend Files（仓库 `C:/Users/Admin1/Desktop/Agent/FrontEnd`）：**

- Modify: `src/api/task-control.ts`
- Modify: `src/api/task-control.spec.ts`
- Modify: `src/types/api.ts`
- Modify: `src/stores/chat.ts`
- Modify: `src/stores/chat.spec.ts`
- Modify: `src/components/business/ConversationList.vue`
- Modify: `src/components/business/ConversationList.spec.ts`
- Modify: `src/views/ChatView.vue`

**Interfaces：**

- Consumes: Task 2 的 active-task endpoint。
- Produces: `ConversationTaskSummary`、`ConversationActiveTaskResponse`。
- Produces: `getConversationActiveTask(conversationId: string) -> Promise<ConversationActiveTaskResponse>`。
- Produces: `chat.upsertAssistantMessage(message: Message)`，按服务端 message ID 去重/合并。

- [ ] Step 1: 写 API 失败测试，断言路径编码、active/recoverable/null 三态解析，不把 task.input 当成契约依赖。
- [ ] Step 2: 写 store 失败测试：同一 message ID 的历史 load、replayed message 和 done 只保留一条并合并完整字段；不同 ID 顺序不变。
- [ ] Step 3: 写 ConversationList/ChatView 失败测试：点击会话写 `/chat?conversation=<id>`；刷新带合法 query 时选择并加载该会话；无效/越权 ID 失败后移除 query，不选择其它会话冒充原目标。
- [ ] Step 4: 实现 API/types/upsert；ChatView 对 query 的 watch 使用 request version，且首次进入必须 `immediate:true`。
- [ ] Step 5: 新建会话成功后用 `router.replace` 写 conversation query；删除当前会话时清除 query。
- [ ] Step 6: 跑相关 Vitest、typecheck 和 lint，提交 `feat(chat): restore selected conversation from url`。

## Task 6：前端 cold attach、事件重建与本地 detach

**Frontend Files：**

- Modify: `src/composables/useChatStream.ts`
- Modify: `src/composables/useChatStream.spec.ts`
- Modify: `src/views/ChatView.vue`
- Modify: `src/components/workspace/WorkspaceShell.vue`
- Modify: `src/components/workspace/WorkspaceShell.spec.ts`

**Interfaces：**

- Consumes: Task 5 的 active-task API 和 upsert；现有 `streamTaskEvents(taskId, {afterSeq})`。
- Produces: `restoreConversation(conversationId: string): Promise<void>`。
- Produces: `detachConversation(conversationId: string): void`，仅 abort 本地 transport。
- Produces: ConvCtx 新字段 `restoreGeneration/restorePromise/restored`，防重复发现和迟到响应。

- [ ] Step 1: 写失败测试 `cold restore starts task event replay from zero`：新 composable 实例发现 running Task，断言 `afterSeq` 缺省/0、历史 tool/message/status 重建、后续 live event 继续处理。
- [ ] Step 2: 写失败测试覆盖 active lookup null、waiting_confirm 恢复弹窗、failed recoverable 恢复 CTA、查询和订阅之间 Task done 后 reload 一次。
- [ ] Step 3: 写失败测试 `restore generation isolates rapid A to B selection`：A 的迟到 lookup/event 不改变 B 当前 state；回 A 时可使用 A 自己的 ctx。
- [ ] Step 4: 写失败测试 `warm conversation switch keeps existing controller and cursor`：组件存活期间 A→B→A 不 abort A，不从 0 重播。
- [ ] Step 5: 写失败测试 `detach aborts transport without cancelling task`：不得调用 `POST /tasks/{id}/cancel`，也不得把 Task 标为 done/cancelled；再次进入走权威 discovery。
- [ ] Step 6: 写失败测试 `discovery gates composer and server conflict reattaches`：lookup 未完成时不能发送；40901 时重新查询并 attach 已存在 Task，不重发原 chat。
- [ ] Step 7: 实现 cold/warm restore、generation 和 detach；confirm/recover/start 替换 controller 前先安全结束旧 events live-tail，避免双订阅。
- [ ] Step 8: ChatView 选择/刷新调用 `setConversation + loadMessages + restoreConversation`；WorkspaceShell 选择同样接入，卸载继续 stop transports 但不取消后端。
- [ ] Step 9: 跑 composable、ChatView、WorkspaceShell、MessageList/MessageBubble 回归和 typecheck/lint，提交 `feat(chat): reattach conversation tasks after refresh`。

## Task 7：工作区 URL 恢复与重启恢复风险提示

**Frontend Files：**

- Modify: `src/components/workspace/WorkspaceShell.vue`
- Modify: `src/components/workspace/WorkspaceShell.spec.ts`
- Modify: `src/views/WorkspaceDetailView.vue`
- Modify: `src/composables/useChatStream.ts`
- Modify: `src/components/common/AgentRunStatus.vue`
- Modify: `src/components/common/AgentRunStatus.spec.ts`
- Modify: `src/components/business/MessageList.vue` 或现有 recoverable action 所在组件

**Interfaces：**

- Consumes: `error.kind=process_restart`、`relation=recoverable`。
- Produces: `/workspace/:id?conversation=<id>` 选择恢复，并验证 conversation 的 `workspace_id` 等于路由 workspace。
- Produces: process-restart 恢复确认文案，明确“未完成工具节点可能重新执行；外部副作用可能重复”。

- [ ] Step 1: 写 WorkspaceShell 失败测试：选择写 query、刷新 query 恢复、切 workspace 清理不属于新 workspace 的 conversation、乱序 list/messages/active-task 响应不污染当前 workspace。
- [ ] Step 2: 写 UI 失败测试：`process_restart + recoverable` 显示“任务因服务重启中断”和“从断点继续”；点击后先出现副作用警告，取消不调用 recover，确认才调用。
- [ ] Step 3: 写 waiting_confirm 刷新回归：恢复 Task 后弹出原确认框，确认/拒绝复用同一 task ID。
- [ ] Step 4: 实现工作区 query 同步、归属验证和风险确认；普通 transport recoverable 保持现有轻量文案。
- [ ] Step 5: 跑 WorkspaceShell/AgentRunStatus/interrupt/recover Vitest、typecheck、lint，提交 `feat(chat): surface restart recovery safely`。

## Task 8：跨阶段集成验收、文档和交付 Gate

**Backend Files：**

- Modify: `README.md`
- Modify: `docs/03-api-contracts.md`
- Create: `progress-conversation-task-recovery.md`
- Test: `tests/test_task_restart_recovery.py`
- Test: `tests/test_tasks_api.py`
- Test: `tests/test_chat_stream.py`
- Test: `tests/test_task_events.py`

**Frontend Files：**

- Modify: `progress.md`
- Test: `src/composables/useChatStream.spec.ts`
- Test: `src/components/workspace/WorkspaceShell.spec.ts`
- Test: `e2e/chat-stream.spec.ts` 或新增 `e2e/chat-refresh-recovery.spec.ts`

- [ ] Step 1: 后端集成测试：A/B 会话各自 Task/事件互不污染；同会话双提交只有一个成功；query→subscribe 间完成仍回放 done。
- [ ] Step 2: 真实进程级测试：启动慢 Task，终止并重启后端，断言没有自动 graph producer；Task 被对账为精确 recoverable 或 nonrecoverable，事件可回放。
- [ ] Step 3: 真实 UI E2E：A 运行→切 B→回 A；A 运行中刷新→URL 选回 A→业务轨迹 cold replay→live-tail→最终 Message，且消息和 Task 各只有一份。
- [ ] Step 4: E2E：waiting_confirm 刷新恢复弹窗；后端重启后显示人工恢复警告；取消警告不执行，确认后从精确 cursor 完成。
- [ ] Step 5: 验证不持久化 token/thinking，刷新后 partial 文本不会伪装回放，完成后以 Message 正文收敛。
- [ ] Step 6: 后端运行 `pytest -q`、`ruff check app tests`、`python -m compileall -q app tests`、`git diff --check`。
- [ ] Step 7: 前端运行 `typecheck`、`lint`、全量 Vitest、Playwright E2E、production build，并验证 build 产物入口依赖完整。
- [ ] Step 8: 使用 `review-test-simplify` 执行 Test/Review/Simplify gate；Critical/High/Medium finding 必须修复或由用户明确接受。
- [ ] Step 9: 更新 backend progress ledger 和 FrontEnd `progress.md`，分别列出 commit、测试命令、结果及剩余边界。
- [ ] Step 10: 后端提交 `docs(task): record refresh and restart recovery delivery`；前端提交相应文档/build 产物，最终两个仓库 `git status --porcelain` 均为空。

---

## 明确不纳入本计划

- 后端重启后自动 spawn/requeue Task。
- Redis、数据库任务队列、worker lease/heartbeat、多实例 cancel routing。
- 对 shell、MCP、数据库和远程 API 提供 exactly-once 保证。
- token/thinking 增量持久化和逐字回放。
- 多设备同步未完成的前端 partial text。
- 长事件流分页、压缩、归档与 TTL 策略调整。

## 审批清单

- [ ] 同意 URL 持久化 conversation ID，Task ID 仍由后端 owner-scoped 查询发现。
- [ ] 同意同一会话服务端最多一个 `pending/running/waiting_confirm` Task，冲突返回 40901。
- [ ] 同意进程重启任务使用现有 `failed` 状态，不新增 `interrupted` 枚举。
- [ ] 同意 pending 或缺少精确 graph cursor 的 running Task 不可恢复，要求重新发送。
- [ ] 同意有精确 cursor 的 orphan Task仅提供人工恢复，并展示外部副作用可能重复的警告。
- [ ] 同意 token/thinking 不回放，最终正文以持久 Message 为准。
