# Interrupt Resume Recovery and Stale Runtime Prevention Plan

**Goal:** 恢复并加固工具确认链路，同时让用户点击确认后立即看到“正在继续/正在执行什么”，顶部状态与实时轨迹准确跟随 Agent 当前步骤。

**Architecture:** 已通过重启验证磁盘上的 legacy `Interrupt` 兼容代码有效，当前事故已解除。后续把 `JsonFileSaver` 收敛到 LangGraph 官方 typed serializer 和版本化 JSON envelope，同时保留所有 v1 记录的只读兼容；确认操作采用“前端即时乐观反馈 + 后端首帧确认 + 失败事务回滚”，并从既有 SSE 事件派生一条实时执行轨迹。后端阻止同一会话在仍有未决确认时启动新图，启动脚本和健康接口增加运行版本指纹，避免旧进程再次被误判为已更新。

**Global Constraints:**

- 本计划阶段只创建计划文件，不修改实现、不重启服务、不恢复任务。
- 执行阶段不得原地批量改写 `C:/Users/Admin1/.LiBao/checkpoints`、`tasks.json` 或会话数据；旧数据只在读取时兼容，新写入使用新格式。
- 不使用 `eval` 或 pickle；legacy `Interrupt.repr` 仅允许受大小、深度和节点数限制的 `ast.literal_eval`。
- 新格式必须使用 `BaseCheckpointSaver.self.serde.dumps_typed/loads_typed`；默认 serializer 使用 strict msgpack allowlist 且 `pickle_fallback=False`。
- `/chat/stream`、`/tasks/{id}/resume` 和既有 SSE 事件字段保持向后兼容；健康接口只增加字段。
- 确认恢复在服务端明确接受前，Task 必须保持 `waiting_confirm`，前端必须保留原 `task_id`、`interrupted` 和工具卡。
- 用户点击确认后的同一 UI tick 内，顶部 phase 必须从 `waiting_confirm` 切到 `resuming`，确认弹窗关闭，原工具卡切到 `running`；若请求未被服务端接受，则完整回滚到可重试的 `waiting_confirm`。
- resume SSE 在执行耗时工具前必须先发送 `accepted=true` 的 running acknowledgement；前端不得等到工具结果或下一段 token 才显示反馈。
- 实时轨迹必须由 SSE 状态派生，不轮询猜测；至少覆盖启动、思考、工具调用、等待确认、确认继续、工具完成/失败、Agent 切换、生成回复和收尾。
- 同一用户、同一 conversation 仍有 `waiting_confirm` Task 时，不得创建新的聊天 Task、持久化新的用户消息或再次驱动同一 graph thread。
- 启动脚本不得因为 8000 端口健康就静默复用未知或过期进程；也不得自动终止无法验证为当前项目实例的进程。
- 保留当前 dirty worktree 和其他 Agent 的未提交修改；不得 reset、checkout 或覆盖无关文件。

---

## Confirmed Diagnosis

- 当前 Uvicorn/Python 后端进程启动于 `2026-08-29 15:53:06`，而 `app/orchestration/checkpointer.py` 修改于 `2026-08-29 16:16:21`。
- `start.cmd:26-29` 和 `start.sh:23-28` 在 health 成功时直接 skip，因此重新运行启动脚本也没有加载新代码。
- 最新故障 checkpoint `b54e09bb-0b64-4023-ae7d-a6ebee019aef.json` 中唯一的 `not_implemented` 位于 `writes.*.__interrupt__`；当前磁盘源码已能只读恢复为 `CheckpointTuple` 和 `Interrupt`。
- 原任务仍为 `waiting_confirm`。确认 HTTP 500 后，前端提前清除了 `interrupted`，随后新消息又创建了 Task 并复用同一 conversation thread，因旧进程再次读取 legacy `Interrupt` 而失败。
- 用户已于 `2026-08-29` 重启后端并实测“同意执行”可以正常继续，证明序列化兼容修复已生效；当前剩余问题是确认后的即时反馈、顶部 phase 更新和实时轨迹可见性。

## Execution Record (2026-08-29)

- Task 1 complete：typed checkpoint envelope、旧 `lc_dumps`/Interrupt repr 只读兼容已落地；JSON saver 定向测试 13 passed。
- Task 2 complete：`60007` 检查点错误信封、同会话待确认 fail-closed、resume 首帧 accepted acknowledgement 已落地；后端定向回归 57 passed，全量回归 676 passed / 4 skipped。
- Task 3 complete：前端确认事务、`resuming` 状态、SSE 活动轨迹、网络对账及弹窗防重复提交已在前端工作区落地；typecheck、Vitest 43 files/223 tests、lint、build 通过；构建产物已同步到 `frontend_dist`。
- Task 4 complete（保守模式）：健康接口新增 runtime identity/checkpoint codec 与 `scripts/check_backend_runtime.py`，启动脚本只在 current 项目实例才允许跳过，stale/legacy/foreign 明确提示并提供人工 `restart` 流程；定向测试 3 passed。未实现自动 kill，避免终止无法验证归属的进程。

---

## Task 0: Controlled incident recovery

**Files:**

- Inspect only: `app/orchestration/checkpointer.py`
- Inspect only: `start.cmd`
- Inspect only: `C:/Users/Admin1/.LiBao/tasks.json`
- Inspect only: `C:/Users/Admin1/.LiBao/checkpoints/b54e09bb-0b64-4023-ae7d-a6ebee019aef.json`

**Interfaces:**

- Consumes: 当前后端进程启动时间、`checkpointer.py` 修改时间、最新 `waiting_confirm` Task 的 `pending_confirm.thread_id`。
- Produces: 一个启动时间晚于修复源码修改时间的后端进程，以及可由当前 `JsonFileSaver` 成功读取的原 checkpoint；不自动批准用户的工具调用。

- [x] Step 1: 已只读记录 `/api/v1/system/health`、旧后端 PID/启动时间、`checkpointer.py` 修改时间、`waiting_confirm` Task 和 thread id；故障 checkpoint 中 `not_implemented` 只位于 `__interrupt__` pending write。
- [x] Step 2: 用户已关闭旧后端并重新启动当前工作区服务；未自动终止无法验证身份的端口进程。
- [x] Step 3: 新 Uvicorn/Python 进程启动于 `2026-08-29 16:48:13`，晚于 `checkpointer.py` 的 `16:16:21` 修改时间；当前 codec 已只读恢复真实 legacy checkpoint 为 `list[Interrupt]`。
- [x] Step 4: 用户已在前端实测 approved resume 能继续执行；最新确认任务进入 `done`，没有再出现 checkpoint 500。
- [ ] Step 5: 用户确认完成后发送一条普通消息；验证没有再创建携带 `Interrupt not_implemented` 错误的 failed Task。

---

## Task 1: Replace ad-hoc checkpoint serialization with a typed, versioned codec

**Files:**

- Create: `app/orchestration/checkpoint_codec.py`
- Modify: `app/orchestration/checkpointer.py:13-320`
- Test: `tests/test_json_file_saver.py`

**Interfaces:**

- Consumes: `SerializerProtocol.dumps_typed(value) -> tuple[str, bytes]`、`SerializerProtocol.loads_typed((type_name, payload)) -> Any`、现有 v1 `lc_dumps` 字符串、现有 `__libao_interrupt__` marker 和 legacy `not_implemented` 记录。
- Produces: `CheckpointDecodeError`；`JsonCheckpointCodec.dumps(value: Any) -> dict[str, str]`；`JsonCheckpointCodec.loads(payload: str | dict[str, Any], *, channel: str | None = None) -> Any`；JSON envelope `{"format":"langgraph-typed-v1","type":"msgpack","data":"BASE64_ENCODED_BYTES"}`。

- [ ] Step 1: 新增 failing test `test_typed_interrupt_pending_write_roundtrip_contains_no_not_implemented`：写入真实 `Interrupt`，断言 JSON 文件包含 `langgraph-typed-v1`、不包含 `not_implemented`，重新创建 saver 后读回同 id/value。
- [ ] Step 2: 新增 failing test `test_typed_checkpoint_metadata_and_messages_roundtrip`：checkpoint、metadata、`AIMessage`、普通 pending write 全部在销毁并重建 saver 后保持类型和值。
- [ ] Step 3: 新增 failing test `test_injected_serializer_is_used_for_checkpoint_metadata_and_writes`：注入记录调用的 spy serializer，断言所有写入和读取都经过 `self.serde`，不再绕过构造参数。
- [ ] Step 4: 新增 legacy 兼容参数化测试，覆盖 v1 普通 `lc_dumps`、legacy `not_implemented` 单对象、数组、现有 `__libao_interrupt__` marker，以及同一文件中 v1/v2 checkpoint 混存；预期全部只读成功且文件内容不被自动重写。
- [ ] Step 5: 新增安全测试：未知 envelope format、非法 base64、`pickle` type、错误 class id、超过 65,536 字符的 repr、超过 16 层或 2,048 节点的字面量、非字符串 interrupt id 均抛 `CheckpointDecodeError`，文件保持不变。
- [ ] Step 6: 运行 `uv run pytest tests/test_json_file_saver.py -q`，确认新增测试在当前实现上按预期失败。
- [ ] Step 7: 实现 `JsonCheckpointCodec`：默认使用 `JsonPlusSerializer(pickle_fallback=False, allowed_msgpack_modules=None)`；只接受 `null/bytes/bytearray/json/msgpack` typed payload；base64 使用严格校验；禁止 `pickle` 和未知 type。
- [ ] Step 8: 将 `JsonFileSaver.put()`、`put_writes()`、`get_tuple()`、`list()` 和 `_checkpoint_before_failed_input()` 的 checkpoint、metadata、pending write 编解码统一切到 codec；`__error__` 先净化为 `{"error_type": type(value).__name__}` 再 typed encode。
- [ ] Step 9: 将文件 `schema_version` 升到 2，但按值识别 envelope，从而允许 v1/v2 混存；保留原子写盘、锁、thread key 和 checkpoint 选择语义。
- [ ] Step 10: 运行 `uv run pytest tests/test_json_file_saver.py -q`，预期全部通过；再用真实故障 checkpoint 做只读 smoke，预期成功且文件哈希前后相同。

---

## Task 2: Make resume and conversation state fail closed

**Files:**

- Modify: `app/core/errors.py`
- Modify: `app/api/routers/tasks.py:148-181`
- Modify: `app/api/routers/chat.py:45-130`
- Modify: `app/orchestration/chat_stream.py:422-590`
- Modify: `app/services/task.py:90-235`
- Modify: `app/storage/repositories/task.py:32-90`
- Test: `tests/test_graph_interrupt.py`
- Test: `tests/test_tasks_api.py`
- Test: `tests/test_chat_stream.py`
- Test: `tests/test_interrupt_stream.py`

**Interfaces:**

- Consumes: `CheckpointDecodeError`、Task 的 `status/input/pending_confirm`、conversation id 和当前用户 id。
- Produces: `ERR_CHECKPOINT_INVALID = 60007`；`TaskRepository.get_waiting_confirm_for_conversation(user_id: UUID, conversation_id: UUID) -> Task | None`；恢复失败时稳定错误信封；未决确认会话的 chat fail-closed 检查；resume 首帧 `status` payload `{status:"running",phase:"tool",detail:tool_name,tool_call_id,accepted:true,message:"已确认，正在执行"}`。

- [ ] Step 1: 新增 graph test `test_json_file_saver_resume_after_process_recreation`：运行到 interrupt 后销毁 graph/saver，重新构建二者，先 `aget_state()` 再 approved resume，断言工具结果 `done`；同样覆盖 denied resume 为 `cancelled`。
- [ ] Step 2: 新增 API integration test `test_sse_resume_reads_real_legacy_interrupt_checkpoint`：使用真实 `JsonFileSaver` 和用户报错同结构的 complex legacy repr，经 `POST /tasks/{id}/resume` 前置 `aget_state()` 后返回 SSE，而不是 HTTP 500。
- [ ] Step 3: 新增 API test `test_resume_decode_failure_preserves_waiting_confirm`：注入畸形 checkpoint，断言返回 code `60007`、不包含原始 repr/payload，Task 仍为 `waiting_confirm` 且 `pending_confirm` 未清空。
- [ ] Step 4: 新增 repository/service test `test_find_waiting_confirm_for_conversation_is_user_scoped`：只返回同 user、同 conversation、状态为 `waiting_confirm` 的最新 Task，忽略 done/failed/cancelled 和其他用户任务。
- [ ] Step 5: 新增 chat route test `test_chat_rejects_new_message_while_conversation_waits_for_confirmation`：存在未决确认时返回 `40902`，不创建新 Task、不追加 user message、不触发 graph。
- [ ] Step 6: 新增 stream test `test_resume_emits_running_ack_before_tool_execution_result`：approved resume 的第一个业务帧必须是 `status` 且 `accepted=true/phase=tool`，包含原 `tool_name/tool_call_id`；让 fake 工具阻塞时仍能先收到该帧，证明 UI 不依赖工具完成才更新。
- [ ] Step 7: 运行上述定点测试，确认当前 route stub、MemorySaver、无会话防线和无 resume acknowledgement 的实现无法满足新增断言。
- [ ] Step 8: 在 resume route 将 `CheckpointDecodeError` 映射为不泄露内部 payload 的 `AppError(60007, "任务检查点无法读取，任务仍保持等待确认")`；异常必须发生在任何状态迁移之前。
- [ ] Step 9: 实现 user-scoped pending-confirm 查询，并在 `/chat/stream` 创建 Task、持久化消息和构造 `StreamingResponse` 之前执行；冲突时返回 `40902` 和明确提示“当前会话仍有待确认操作，请先确认或拒绝”。
- [ ] Step 10: `resume_stream_events()` 在 approved Task 成功切到 running 后、启动 graph 之前立即 yield `status` acknowledgement `{status:"running",phase:"tool",detail:pending.tool_name,tool_call_id:pending.tool_call_id,accepted:true,message:"已确认，正在执行"}`；denied 分支发送 `status/cancelling` 且 `accepted=true`，不得伪装为正在执行工具。
- [ ] Step 11: 运行 `uv run pytest tests/test_graph_interrupt.py tests/test_tasks_api.py tests/test_chat_stream.py tests/test_interrupt_stream.py -q`，预期全部通过。

---

## Task 3: Make confirmation feedback immediate and expose live execution progress

**Files:**

- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/api/sse.ts:1-112`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/api/task-control.ts`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/composables/useChatStream.ts:24-88,260-445,497-523`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/common/AgentRunStatus.vue`
- Create: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/common/LiveRunTrace.vue`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/business/InterruptConfirmDialog.vue`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/trajectory/TrajectoryPanel.vue`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/views/ChatView.vue`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/workspace/WorkspaceShell.vue`
- Test: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/composables/useChatStream.spec.ts`
- Test: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/api/sse.spec.ts`
- Test: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/common/AgentRunStatus.spec.ts`
- Test: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/common/LiveRunTrace.spec.ts`
- Test: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/business/InterruptConfirmDialog.spec.ts`
- Test: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/trajectory/TrajectoryPanel.spec.ts`

**Interfaces:**

- Consumes: REST error envelope `{code,message,data,trace_id}`、SSE `status/thinking/tool_call/tool_result/agent_switch/token/message/done/error`、现有 `InterruptInfo` 和 `taskId`。
- Produces: `SseRequestError`（保留 HTTP status、业务 code 和 message）；`getTaskStatus(taskId: string) -> Promise<TaskStatus>`；`AgentRunPhase` 新值 `resuming`；stream state `confirming: boolean`、`activities: LiveRunActivity[]`；每个 `ConvCtx` 私有 `resumeSnapshot` 与 `resumeAccepted`；`LiveRunActivity={id,kind,label,detail,status,startedAt,finishedAt?,toolCallId?}`。

- [ ] Step 1: 新增 `sse.ts` failing tests：非 2xx JSON 响应、HTTP 200 但 `code != 0` 的 REST envelope、非 JSON 错误文本都调用 `onError` 并保留服务端 message；不得把 REST envelope 交给 `onEvent` 冒充 SSE。
- [ ] Step 2: 新增 composable failing test `approved_resume_updates_phase_and_tool_card_synchronously`：调用 `confirmInterrupt(true)` 后无需等待 Promise/SSE，立即断言 `phase=resuming`、`phaseDetail=shell`、`confirming=true`、弹窗数据从可见 state 移入 `resumeSnapshot`、原工具卡为 `running`，activities 新增“已确认，正在继续执行 shell”。
- [ ] Step 3: 新增 composable failing test `resume_ack_transitions_to_live_tool_execution`：收到后端 `{type:"status",payload:{accepted:true,phase:"tool",detail:"shell"}}` 后，丢弃 snapshot、`confirming=false`、顶部切为“正在执行 · shell”，activity 保持 running；工具结果前不得回退为“等待确认”。
- [ ] Step 4: 新增 composable failing test `resume_http_failure_restores_interrupt_and_allows_retry`：第一次 resume 在响应建立前收到明确 HTTP/REST 错误，完整恢复原 `taskId/interrupted/waiting_confirm/awaiting_confirm`，`confirming=false`，activity 标记“继续执行失败，可重试”，第二次点击仍使用同一 task id。
- [ ] Step 5: 新增 composable failing test `resume_network_failure_reconciles_task_before_retry`：ack 前网络断线属于不确定结果，先调用 `GET /tasks/{id}`；状态为 `waiting_confirm` 才恢复弹窗，`running` 保持“执行中（连接已中断）”且禁止重复 resume，`done/failed/cancelled` 收敛到对应终态。
- [ ] Step 6: 新增 activity reducer tests：thinking chunk 合并为单条；同 `tool_call_id` 的 awaiting/running/done 更新同一条而非重复追加；token 只在首块创建“生成回复”；agent switch、finalizing、done/error 有明确终态；每会话最多保留 50 条。
- [ ] Step 7: 新增 `AgentRunStatus` test：`resuming` 显示“已确认，正在继续”，`tool + detail=shell` 显示“正在执行 · shell”，二者均为 active spinner；状态变化通过 `aria-live=polite` 宣告。
- [ ] Step 8: 新增 `LiveRunTrace`/`TrajectoryPanel` tests：聊天模式和“轨迹”模式都显示“当前执行（实时）”及最近步骤；运行项显示 elapsed time；live 区域与持久轨迹分区展示，不跨区逐项合并；终态后只在最后一次 REST refresh 成功时隐藏整个 live 区域。
- [ ] Step 9: 新增 conversation lifecycle tests：activities/resume snapshot 按 `ConvCtx` 隔离；`setConversation()` 不串状态；新 run 的 `resetCtx()` 清空旧 activities/snapshot；`stopAll()` 清理所有 snapshot/timer。
- [ ] Step 10: 新增 dialog test：`confirming=true` 时确认与拒绝按钮均禁用，确认按钮显示 loading；失败回滚后弹窗自动重开且按钮可用。
- [ ] Step 11: 运行 `npm run test:unit -- src/api/sse.spec.ts src/composables/useChatStream.spec.ts src/components/common/AgentRunStatus.spec.ts src/components/common/LiveRunTrace.spec.ts src/components/business/InterruptConfirmDialog.spec.ts src/components/trajectory/TrajectoryPanel.spec.ts`，确认新增测试失败。
- [ ] Step 12: 实现 `SseRequestError` 和统一响应体解析；网络错误、HTTP 错误、REST 业务错误分别保留可读 message，响应解析失败时退回 `stream failed: <status>`；实现 `getTaskStatus()` 供不确定网络结果对账。
- [ ] Step 13: 将 `confirmInterrupt()` 改为可回滚的乐观事务：同步保存 snapshot、关闭弹窗、切 `resuming`、更新工具卡和 activity；仅 `accepted=true` acknowledgement 或其后的 `tool_result/token/message/done/error` 构成服务端接受证据并提交 snapshot。明确 HTTP/REST 拒绝直接回滚；ack 前网络断线必须查询 Task 状态后收敛，禁止盲目重复 resume。
- [ ] Step 14: 明确 `confirming` 生命周期：点击时为 true；收到接受证据、明确拒绝或状态对账完成时复位 false；terminal event 再次幂等复位。收到 ack 后 phase 从本地 `resuming` 切到服务端 `tool`，不存在两种文案竞争。
- [ ] Step 15: 实现 activity reducer 与 `LiveRunTrace`，从既有 SSE 事件构建稳定、去重、每会话隔离的实时轨迹；不得将 reasoning 原文复制到状态标题，只显示“思考中”和已有 thinking 区块。
- [ ] Step 16: `AgentRunStatus` 增加 `resuming` 与 tool detail 文案；ChatView/WorkspaceShell 不再在 handler 中抢先手工关闭弹窗，而由 stream transaction 驱动，并同时渲染 `LiveRunTrace`。
- [ ] Step 17: `TrajectoryPanel` 接收 `liveActivities`，在 REST 持久轨迹上方显示独立“当前执行（实时）”区域；继续保留 2.5 秒 persisted trajectory 轮询作为历史落库同步，不用它驱动当前 phase。终态后的首次成功 refresh 直接隐藏整个 live 区域，避免依赖历史节点是否具备 tool id。
- [ ] Step 18: 运行定点 Vitest，预期通过；再运行 `npm run typecheck` 和 `npm run lint:check`。

---

## Task 4: Detect stale backend code instead of silently reusing it

**Files:**

- Create: `app/core/runtime_info.py`
- Create: `scripts/check_backend_runtime.py`
- Modify: `app/api/routers/system.py:27-34`
- Modify: `start.cmd:18-45`
- Modify: `start.sh:18-36`
- Modify: `README.md:6-40`
- Test: `tests/test_runtime_info.py`
- Test: `tests/test_backend_runtime_check.py`
- Test: `tests/test_system_health.py`

**Interfaces:**

- Consumes: 进程启动时刻、当前项目根的规范化路径、`app/**/*.py` 最新 mtime、health URL。
- Produces: additive health field `runtime={pid,started_at,instance_id,source_mtime_ns,restart_required,checkpoint_codec}`；CLI 状态 `absent/current/stale/foreign/legacy`；显式 `start.cmd restart` / `start.sh restart` 流程。

- [ ] Step 1: 新增 runtime info failing tests：源码 mtime 未变化时 `restart_required=false`，晚于启动快照时为 true；`instance_id` 对大小写和目录分隔符规范化后稳定，响应不暴露绝对项目路径。
- [ ] Step 2: 新增 health failing test：`GET /api/v1/system/health` 保留既有 status/service/env/time，并增加 runtime 字段；`checkpoint_codec` 固定为 `langgraph-typed-v1`。
- [ ] Step 3: 新增 checker failing tests，mock health 响应分别覆盖不可达、当前实例、源码过期、其他工作区实例和缺少 runtime 的旧服务，断言输出状态依次为 `absent/current/stale/foreign/legacy`。
- [ ] Step 4: 运行 `uv run pytest tests/test_runtime_info.py tests/test_backend_runtime_check.py tests/test_system_health.py -q`，确认当前 health/launcher 无法满足测试。
- [ ] Step 5: 实现 runtime snapshot：启动时记录 UTC 时间和 source mtime；health 请求只做轻量 mtime 比较；`instance_id` 使用规范化项目根 SHA-256 截断值，不返回原始路径。
- [ ] Step 6: 实现共享 checker，并让 `start.cmd/start.sh` 使用其结果：`current` 才允许 skip；`absent` 正常启动；`stale` 明确要求 restart；`foreign` 拒绝终止；`legacy` 因无法验证实例身份而只提示手工关闭旧窗口。
- [ ] Step 7: 实现显式 `restart`：仅当 health 的 `service=agent-backend` 且 `instance_id` 与当前项目一致时，才按 health 返回 PID 终止该进程树并等待端口释放；验证失败时不 kill。
- [ ] Step 8: 更新 README，写明普通启动、显式 restart、旧版 health 的一次性手动重启和 `restart_required` 含义；不得推荐生产模式使用 Uvicorn `--reload`。
- [ ] Step 9: 运行三个定点测试，并分别人工验证 `current` 不重复启动、`stale` 不再显示“All up”、`foreign/legacy` 不被自动终止。

---

## Task 5: Full regression, frontend build, and handoff

**Files:**

- Modify: `progress.md`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/progress.md`
- Generate from frontend build: `frontend_dist/index.html`, `frontend_dist/assets/*`

**Interfaces:**

- Consumes: Tasks 0-4 的 typed codec、route guard、transactional resume 和 runtime freshness contract。
- Produces: 后端静态托管可直接使用的前端构建、完整测试记录、前后端交接记录和人工验收步骤。

- [ ] Step 1: 运行后端定点集 `uv run pytest tests/test_json_file_saver.py tests/test_graph_interrupt.py tests/test_tasks_api.py tests/test_chat_stream.py tests/test_interrupt_stream.py tests/test_runtime_info.py tests/test_backend_runtime_check.py tests/test_system_health.py -q`。
- [ ] Step 2: 运行 `uv run pytest -q`、`uv run ruff check app tests scripts`、`uv run python -m compileall -q app tests scripts` 和 `git diff --check`；记录通过数与环境型 skip，不把 warning 写成通过失败。
- [ ] Step 3: 在 `C:/Users/Admin1/Desktop/Agent/FrontEnd` 运行 `npm run typecheck`、`npm run test:unit`、`npm run lint:check`、`npm run build`；把构建产物同步到后端 `frontend_dist`，以新 `index.html` 引用的新 hash assets 为准。
- [ ] Step 4: 通过显式 restart 启动新后端，断言 health 的 `started_at` 晚于源码修改、`restart_required=false`、`checkpoint_codec=langgraph-typed-v1`。
- [ ] Step 5: 新建测试会话执行真实闭环：shell 调用触发 interrupt → 点击 approved 后 100ms 内顶部离开“等待确认”并显示“已确认，正在继续/正在执行 shell” → 实时轨迹出现确认与工具 running 节点 → 模拟一次 resume HTTP 失败并自动恢复弹窗/task id → 重试 approved → 工具完成 → 轨迹进入生成回复/已完成 → 随后普通消息成功；断言没有 raw repr、`not_implemented`、重复 Task 或持续卡住的 waiting_confirm。
- [ ] Step 6: 不自动操作用户原任务；把“重新点击原确认、确认后发送新消息”的验收交给用户，并只读核对 Task 终态和 checkpoint 新写入格式。
- [ ] Step 7: 更新两个 progress 文件，记录根因、接口契约、测试结果、生成产物和仍需用户完成的人工验收；不覆盖已有未提交交接内容。
