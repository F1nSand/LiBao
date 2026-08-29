# Long-Running Model Stream Recovery Implementation Plan

**Goal:** 长时间 Agent 运行遭遇模型流式连接中断时，只重跑失败的模型节点、保留已完成工具结果与会话轨迹，并让前端能够可靠对账、补回业务事件和从断点继续，而不重新提交原用户消息。

**Architecture:** 将模型异常在 `agent_execute` 边界归一化为结构化错误，并由 `stream_graph_events` 对明确的模型传输错误自动恢复一次：从 `JsonFileSaver` 显式选取失败节点输入 checkpoint，以 `initial=None`、同一 thread 和明确 `checkpoint_id` 重新进入图。任务业务事件使用独立的 task-level 单调序号持久化到 JSONL，SSE 断线后通过 `after_seq` 补发；逐 token/thinking 不持久化，终态通过已持久化消息收敛。自动恢复仍失败时，Task 保存 `recoverable` 错误，用户可调用幂等的 `/tasks/{id}/recover` 从同一 checkpoint 继续；普通聊天使用专门的恢复流完成会话消息落库，后台任务使用后台恢复器。

**Global Constraints:**
- 不在 Provider 模型或 API 契约上增加上下文窗口、视觉能力或超时字段。
- 不把 256K/1M 写成模型真实上下文能力，不因估算值拒绝、裁剪或改变请求；本轮只观测上下文规模。
- `llm_stream_chunk_timeout_s` 默认 300 秒；`ChatOpenAI.max_retries` 固定为 0，重试只能由本应用的节点级策略发起。
- 自动重试上限固定为 1 次，只适用于明确发生在 `agent_execute` 的模型传输错误；工具节点、未知节点、鉴权、参数、上下文超限和业务拒绝不得自动重试。
- 手动断点恢复最多 3 次；同一 idempotency key 或并发请求最多启动一个恢复运行。
- 恢复必须使用同一 thread、显式失败 checkpoint 和 `initial=None`；禁止重新 POST 原 `/chat/stream`，禁止重新追加用户消息，禁止重跑已成功工具。
- 普通聊天 thread 解析顺序固定为 `pending_confirm.thread_id -> task.input.conversation_id -> task.id`；确认恢复的旧解析语义保持兼容。
- 第一次失败尝试产生的未封口 token/thinking 不进入 Message/checkpoint；重试事件要求前端只清除未持久化的 partial segment，已封口 assistant/tool 轮次必须保留。
- 持久任务事件只包含 `message_start/model_retry/status/message/tool_call/tool_result/agent_switch/interrupt/done/error/cancelled`；不得持久化 token、thinking、提示词正文、API key、图片 base64 或文档正文。
- 所有错误 `details` 仅保存类型、计数、持续时间和脱敏后的模型标识；原始响应体、请求头、URL query、凭证和用户正文不得进入日志、Task.error 或 SSE。
- 工具完整 `output` 维持现有 state/checkpoint/展示契约；只有送给模型的 `summary` 统一受 `tool_result_max_chars` 限制，本轮不引入新的工具输出对象存储。
- 保留当前工作树中的用户和其他 Agent 改动；不得 reset、checkout、覆盖或顺手格式化无关文件。
- 使用 TDD：每个行为先写失败测试，定向测试转绿后再跑相关回归；执行阶段结束前必须使用 `review-test-simplify` 完成 Test/Review/Simplify 三道 gate。

---

## Task 1: 结构化模型错误与显式流式超时

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/core/errors.py`
- Modify: `app/core/llm.py`
- Modify: `app/orchestration/nodes/agent_execute.py`
- Modify: `.env.example`
- Test: `tests/test_llm.py`
- Test: `tests/test_agent_nodes.py`

**Interfaces:**
- Produces: `LLMFailureKind(StrEnum)`，至少包含 `transport`、`context_length`、`authentication`、`rate_limit`、`invalid_request`、`unknown`。
- Produces: `LLMTransportError(AppError)`，固定 `code=60008`、`kind="llm_transport"`、`retryable=True`、`recoverable=True`，并持有 JSON-safe `details: dict[str, Any]`。
- Produces: `classify_llm_exception(exc: Exception) -> LLMFailureKind`，优先按异常类型/异常链分类，文本兜底只识别 `incomplete chunked read`、`peer closed connection`、`No streaming chunk received` 和明确 context-length 文案。
- Produces: `normalize_llm_exception(exc: Exception, *, model: str, context_metrics: dict[str, Any]) -> AppError`。
- Produces: `Settings.llm_stream_chunk_timeout_s: float = 300.0` 与 `Settings.llm_transport_auto_retries: int = 1`；校验 timeout `> 0`、auto retries 只能为 `0` 或 `1`。
- Consumes: Task 2 的 `context_metrics`；Task 2 完成前测试可传最小字典。

- [ ] Step 1: 在 `tests/test_llm.py` 写 `test_build_model_disables_sdk_retries_and_sets_stream_idle_timeout`，断言 `LLMService.build_model()` 向 `ReasoningChatOpenAI` 传 `max_retries=0` 和 `stream_chunk_timeout=300.0`，不传 `max_tokens` 或上下文窗口。
- [ ] Step 2: 在 `tests/test_llm.py` 参数化写 `test_classify_llm_transport_failures`，覆盖 `httpx.RemoteProtocolError`、`httpx.ReadTimeout`、异常链中的 `openai.APIConnectionError`，以及当前两条真实错误文本；断言均分类为 `transport`。
- [ ] Step 3: 在 `tests/test_llm.py` 写 `test_context_and_auth_errors_are_not_transport_recoverable`，覆盖 maximum context length、HTTP 400 参数错误、401/403、429；断言不会生成 `LLMTransportError`。
- [ ] Step 4: 在 `tests/test_llm.py` 写 `test_normalized_transport_error_redacts_payload`，给异常消息注入 API key、URL query 和大段响应正文，断言 `details` 只含 `model/chunks_received/idle_seconds/elapsed_ms/context_metrics` 等白名单字段且序列化后不含秘密值。
- [ ] Step 5: 运行 `pytest tests/test_llm.py -q`，预期新测试 FAIL，现有 URL/推理内容适配测试仍 PASS。
- [ ] Step 6: 在 `Settings` 增加两个字段和校验；`LLMService.build_model` 显式传 `max_retries=0`、`stream_chunk_timeout=settings.llm_stream_chunk_timeout_s`，不设置 `max_tokens`、`context_window` 或未知模型的硬限制。
- [ ] Step 7: 在 `app/core/errors.py` 实现错误类型和白名单序列化；在 `agent_execute_node` 保留“明确视觉拒绝”优先级，其后将其他模型异常交给 `normalize_llm_exception`，非传输错误保持不可自动恢复。
- [ ] Step 8: 运行 `pytest tests/test_llm.py tests/test_agent_nodes.py -q`，预期 PASS。
- [ ] Step 9: 运行 `ruff check app/core/config.py app/core/errors.py app/core/llm.py app/orchestration/nodes/agent_execute.py tests/test_llm.py tests/test_agent_nodes.py`，修正本任务引入的问题。

---

## Task 2: 上下文规模与流式尝试观测

**Files:**
- Create: `app/orchestration/context_metrics.py`
- Modify: `app/orchestration/nodes/agent_execute.py`
- Modify: `app/orchestration/stream_core.py`
- Test: `tests/test_context_metrics.py`
- Test: `tests/test_stream_core.py`
- Test: `tests/test_agent_nodes.py`

**Interfaces:**
- Produces: `measure_context(messages: Sequence[BaseMessage], tools: Sequence[dict[str, Any]]) -> dict[str, Any]`。
- Produces metrics: `message_count/text_chars/tool_schema_chars/image_count/document_chars/estimated_prompt_tokens/estimated/estimate_method`，其中 `estimate_method="unicode_heuristic_v1"`。
- Produces: ASCII 字符按 `ceil(n/4)`、CJK 字符按 `n`、其他 Unicode 按 `ceil(n/2)` 的确定性估算；图片 base64/URL 不计入文本 token，只增加 `image_count`。
- Produces: 每次模型尝试的 `StreamAttemptMetrics`，包含 `attempt/chunk_count/text_chars/reasoning_chars/started_at/first_chunk_at/last_chunk_at/last_chunk_age_ms/elapsed_ms`。
- Produces: `status` 进度事件每 15 秒最多一条，payload 为 `{status:"running", phase:"model_streaming", attempt, chunks_received, elapsed_ms, last_chunk_age_ms, context_metrics}`。
- Consumes: Task 1 的 `LLMTransportError.details`，最终错误附带最后一次 attempt metrics。

- [ ] Step 1: 创建 `tests/test_context_metrics.py`，写 `test_measure_context_counts_text_blocks_and_tool_schema`，以中英混合消息、System/Human/ToolMessage 和两个工具 schema 验证所有计数字段及确定性估算。
- [ ] Step 2: 写 `test_measure_context_does_not_copy_image_or_document_payload`，输入 image URL/base64 和文档来源块，断言结果只含计数/字符数，序列化结果不含 nonce、base64 或正文片段。
- [ ] Step 3: 在 `tests/test_agent_nodes.py` 写 `test_agent_execute_attaches_context_metrics_to_success_log_and_failure`，断言成功 run_log.input 含 metrics；传输异常携带同一 metrics，即使没有 usage_metadata 也能观测。
- [ ] Step 4: 在 `tests/test_stream_core.py` 写可控 chunk 模型测试 `test_stream_attempt_metrics_count_text_reasoning_and_idle_time`，用 fake clock 验证首末 chunk、thinking、elapsed 和 last-chunk age。
- [ ] Step 5: 写 `test_model_stream_progress_is_throttled_to_15_seconds`，运行 45 秒 fake stream，断言最多 3 条进度事件且不包含 token 正文。
- [ ] Step 6: 运行 `pytest tests/test_context_metrics.py tests/test_agent_nodes.py tests/test_stream_core.py -q`，预期 FAIL。
- [ ] Step 7: 实现 `context_metrics.py`；`agent_execute_node` 只构建一次 `messages = build_context(...)`，在 `ainvoke` 前度量并将同一 messages 传给模型，避免观测改变请求。
- [ ] Step 8: 在 `stream_core` 用每 attempt 独立对象统计 chunk；错误路径把 metrics 合并进结构化错误 details，日志使用字段化参数，禁止输出 chunk 文本。
- [ ] Step 9: 运行本任务定向测试，预期 PASS；再运行 `pytest tests/test_chat_stream.py tests/test_interrupt_stream.py -q`，确保事件顺序和中断路径没有回归。
- [ ] Step 10: 运行 `ruff check app/orchestration/context_metrics.py app/orchestration/nodes/agent_execute.py app/orchestration/stream_core.py tests/test_context_metrics.py tests/test_agent_nodes.py tests/test_stream_core.py`。

---

## Task 3: 显式选择失败节点 checkpoint

**Files:**
- Modify: `app/orchestration/checkpointer.py`
- Modify: `app/orchestration/checkpoint_codec.py`
- Test: `tests/test_json_file_saver.py`
- Test: `tests/test_graph_interrupt.py`

**Interfaces:**
- Produces: `JsonFileSaver.get_failed_config(config: RunnableConfig) -> RunnableConfig | None`。
- Produces: `JsonFileSaver.aget_failed_config(config: RunnableConfig) -> RunnableConfig | None`。
- Contract: 返回同一 `thread_id` 下最新一条包含 `__error__` pending write 的 checkpoint config，并显式写入 `configurable.checkpoint_id`；不得调用 `_checkpoint_before_failed_input`，不得改写/删除原 checkpoint 或 writes。
- Contract: 普通 `get_tuple/aget_tuple/list/alist` 继续沿用当前“跳过失败输入，便于用户发送下一条消息”的兼容逻辑。
- Consumes: 当前 typed checkpoint envelope 与 legacy `__interrupt__` 兼容逻辑，不改变 codec 格式。

- [ ] Step 1: 在 `tests/test_json_file_saver.py` 写 `test_get_failed_config_returns_exact_error_checkpoint_without_default_rollback`，构造 success checkpoint、失败节点输入 checkpoint 和 `__error__` writes，断言返回 checkpoint_id 是失败节点输入而普通 `get_tuple` 仍返回旧兼容位置。
- [ ] Step 2: 写 `test_get_failed_config_is_thread_scoped_and_returns_none_without_error_write`，覆盖另一 thread、未知 checkpoint、畸形 error write。
- [ ] Step 3: 写 `test_get_failed_config_reads_typed_v2_and_legacy_v1_error_records`，确保当前用户文件升级前后的记录均可恢复。
- [ ] Step 4: 在 `tests/test_graph_interrupt.py` 写 `test_failed_agent_node_can_resume_with_none_and_explicit_checkpoint`，模型第一 attempt 抛 transport、第二次成功；断言同一 user 消息只有一份，失败前已完成 ToolMessage 不重复。
- [ ] Step 5: 运行 `pytest tests/test_json_file_saver.py tests/test_graph_interrupt.py -q`，预期 FAIL。
- [ ] Step 6: 实现同步/异步查询方法，复用 codec 解码和 records lock；返回 config 的其他 configurable 键保持原值，只覆盖 `checkpoint_id`。
- [ ] Step 7: 运行定向测试，预期 PASS；只读调用新方法检查真实失败 conversation `b1c453e0-aeee-46b8-8985-66fff5389e40` 时不得改写 `~/.LiBao` 文件。
- [ ] Step 8: 运行 `ruff check app/orchestration/checkpointer.py app/orchestration/checkpoint_codec.py tests/test_json_file_saver.py tests/test_graph_interrupt.py`。

---

## Task 4: 持久化任务业务事件与断线补发

**Files:**
- Create: `app/services/task_events.py`
- Modify: `app/storage/models/task.py`
- Modify: `app/storage/file/store.py`
- Modify: `app/services/task.py`
- Modify: `app/core/events.py`
- Modify: `app/api/routers/tasks.py`
- Modify: `app/services/serializers.py`
- Test: `tests/test_task_events.py`
- Test: `tests/test_tasks_api.py`

**Interfaces:**
- Produces: `Task.last_event_seq: int = 0`，旧 tasks.json 缺字段时默认 0。
- Produces: task event JSONL `task_events/<task_id>.jsonl`，记录 `{task_seq,type,ts,payload}`。
- Produces: `publish_task_event(task_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]`；在 task 级锁内递增 `last_event_seq`、append JSONL、flush Task、再 fan-out live queue，并返回持久记录。
- Produces: `list_task_events(task_id: str, after_seq: int) -> list[dict[str, Any]]`。
- Produces: SSE envelope 可选顶层 `task_seq`；连接内 `seq` 仍从 1 递增，跨连接去重只使用 `task_seq`。
- Produces: `GET /tasks/{id}/events?after_seq=N`，同时接受 `Last-Event-ID: <task_id>:<task_seq>`；query 优先，非法/负数返回 422。
- Contract: 路由先 subscribe，再读取持久事件并记住最大 cursor，随后 live-tail 丢弃 `task_seq <= cursor`，消除“读历史/订阅”竞态。
- Contract: `serialize_task` 返回 `last_event_seq` 和完整结构化 error；失败回放不得再把 `retryable` 硬编码为 false。

- [ ] Step 1: 创建 `tests/test_task_events.py`，写 `test_publish_task_event_persists_monotonic_task_seq_across_restart`，重建 service/store 后继续发布，断言 seq 不重置且 JSONL 可补发。
- [ ] Step 2: 写 `test_task_event_store_rejects_non_business_or_sensitive_payload`，断言 token/thinking 类型不持久化；含 `api_key/base64/prompt/messages` 键的 payload 被白名单清洗或拒绝。
- [ ] Step 3: 写 `test_subscribe_then_replay_has_no_gap_or_duplicate`，在 subscribe 与 replay 之间发布事件，断言调用方按 task_seq 得到恰好一次。
- [ ] Step 4: 在 `tests/test_tasks_api.py` 写 `test_task_events_after_seq_replays_business_events_then_live_tail`，依次发布 status/tool_result/done，断开后用 after_seq 重连，断言只补后两条且 task_seq 单调。
- [ ] Step 5: 写 `test_task_events_accepts_last_event_id_and_failed_snapshot_keeps_recoverable`，断言错误的 kind/retryable/recoverable/details 原样以安全字段返回。
- [ ] Step 6: 运行 `pytest tests/test_task_events.py tests/test_tasks_api.py -q`，预期 FAIL。
- [ ] Step 7: 实现 task event service；保留 `push_event` 为兼容薄封装，内部改调 `publish_task_event`，现有 subscribe/unsubscribe 调用无需一次性迁移。
- [ ] Step 8: 修改事件 envelope、Task 序列化和 events 路由；token/thinking 继续只走原聊天连接，不写 JSONL。
- [ ] Step 9: 运行定向测试，预期 PASS；再运行 `pytest tests/test_notifications.py tests/test_cancel_inflight.py -q` 验证终态哨兵和取消事件。
- [ ] Step 10: 运行 `ruff check app/services/task_events.py app/storage/models/task.py app/storage/file/store.py app/services/task.py app/core/events.py app/api/routers/tasks.py app/services/serializers.py tests/test_task_events.py tests/test_tasks_api.py`。

---

## Task 5: 节点级自动恢复、partial reset 与失败 RunLog

**Files:**
- Modify: `app/orchestration/stream_core.py`
- Modify: `app/orchestration/chat_stream.py`
- Modify: `app/orchestration/task_run.py`
- Modify: `app/core/events.py`
- Modify: `app/storage/repositories/run_log.py`
- Test: `tests/test_llm_transport_retry.py`
- Test: `tests/test_chat_stream.py`
- Test: `tests/test_interrupt_stream.py`

**Interfaces:**
- Produces: `stream_graph_events(..., task_event_sink: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None, auto_retry_limit: int | None = None, round_offset: int = 0)`。
- Produces event: `model_retry` payload `{attempt:2,max_attempts:2,reset_partial:true,reason:"llm_transport",message:"模型连接中断，正从最近断点重试"}`。
- Contract: 第一次 `LLMTransportError` 且 `auto_retry_limit=1` 时，从 Task 3 的 failed config 以 `graph.astream(None, retry_config, ...)` 重启 producer；不调用 on_error、不把 Task 置 failed。
- Contract: 第二次失败、没有 failed config、取消请求或任何非 transport 错误立即走 on_error；工具异常永远不进入该分支。
- Produces: `persist_failed_llm_run(...)` 在 on_error 当下写 `RunLog(status="error", type="llm")`，input 只含 model/context metrics/attempt，output 只含 error kind/chunk/idle/elapsed。
- Consumes: Task 4 的 event sink；所有业务边界事件持久化，token/thinking 不持久化。

- [ ] Step 1: 创建 `tests/test_llm_transport_retry.py`，写 `test_transport_failure_auto_retries_once_from_failed_agent_checkpoint`，模型 first attempt 在输出多个 chunk 后断开、second attempt 成功；断言 graph 输入用户消息一次、已完成工具执行一次、事件含 model_retry 后 done。
- [ ] Step 2: 写 `test_model_retry_resets_only_uncommitted_partial_round`，第一 attempt 输出 `partial-secret-nonce` 后失败，断言 nonce 不进入 Message/checkpoint/final response，已封口 tool round 保留且 round 编号连续。
- [ ] Step 3: 参数化写 `test_auto_retry_never_runs_for_tool_or_non_transport_error`，覆盖 tool handler 超时、context length、1210 参数错误、401、429、取消；断言无 model_retry 且调用次数为 1。
- [ ] Step 4: 写 `test_second_transport_failure_becomes_recoverable_task_error_and_failed_run_log`，断言 auto retry 恰好一次，Task.error 含 `code=60008/kind=llm_transport/retryable=true/recoverable=true`，RunLog 记录两次 attempt 指标且不含文本正文。
- [ ] Step 5: 在 `tests/test_chat_stream.py` 更新精确事件顺序契约，加入可选 `model_retry` 类型但保持无错误正常流字节兼容；在 `tests/test_interrupt_stream.py` 断言确认恢复中的 transport 自动重试仍保持同一 Task/thread。
- [ ] Step 6: 运行 `pytest tests/test_llm_transport_retry.py tests/test_chat_stream.py tests/test_interrupt_stream.py -q`，预期 FAIL。
- [ ] Step 7: 将 `stream_graph_events.producer` 改为 attempt loop；每次 attempt 重置 StreamAttemptMetrics，consumer 收到 model_retry 时清空 pending 未封口 round 状态但不修改 round_sink/已持久化消息。
- [ ] Step 8: 为 chat/task/resume 三条路径注入 task event sink；每 15 秒的模型 progress、model_retry 和业务边界事件写 Task event，token/thinking 仅保留当前 SSE。
- [ ] Step 9: 在 chat/task on_error 立即持久化失败 RunLog，再调用结构化 `TaskService.set_failed`；成功 on_final 不重复落失败 log。
- [ ] Step 10: 运行定向测试，预期 PASS；运行 `pytest tests/test_cancel_inflight.py tests/test_graph_interrupt.py tests/test_tasks_api.py -q` 验证取消/中断/任务事件回归。
- [ ] Step 11: 运行 `ruff check app/orchestration/stream_core.py app/orchestration/chat_stream.py app/orchestration/task_run.py app/core/events.py app/storage/repositories/run_log.py tests/test_llm_transport_retry.py tests/test_chat_stream.py tests/test_interrupt_stream.py`。

---

## Task 6: 幂等“从断点继续”API 与聊天/后台双轨恢复

**Files:**
- Modify: `app/api/schemas/tasks.py`
- Modify: `app/api/routers/tasks.py`
- Modify: `app/services/task.py`
- Modify: `app/storage/models/task.py`
- Modify: `app/storage/repositories/task.py`
- Modify: `app/storage/repositories/message.py`
- Modify: `app/orchestration/chat_stream.py`
- Modify: `app/orchestration/task_run.py`
- Modify: `app/orchestration/task_worker.py`
- Test: `tests/test_tasks_api.py`
- Test: `tests/test_llm_transport_retry.py`
- Test: `tests/test_chat_stream.py`

**Interfaces:**
- Produces: `Task.recovery_attempts: int = 0`、`Task.recovery_key: str | None = None`，旧记录兼容默认值。
- Produces: `TaskService.resolve_execution_thread(task: Task) -> str`，顺序严格为 `pending_confirm.thread_id -> task.input.conversation_id -> task.id`；原 `resolve_resume_thread` 委托该方法但保留名称兼容。
- Produces: `TaskRecoverRequest(BaseModel)`，字段 `idempotency_key: str = Field(min_length=8,max_length=128)`。
- Produces: `TaskService.recover_precheck(db, task, idempotency_key) -> Literal["start","already_running"]`；仅 `failed + error.recoverable=true + recovery_attempts<3` 可转 running，使用 task transition lock 做 CAS。
- Produces: `POST /tasks/{id}/recover`；`Accept:text/event-stream` 且 `task.input.conversation_id` 存在时返回 `retry_stream_events`，其他情况启动 `recover_task_graph` 并返回 `{task_id,status:"running"}`。
- Produces: `retry_stream_events(...)`：重新水合 task.input 的 attachment_ids/file_refs/document context，获取显式 failed checkpoint，以 `initial=None` 续跑；不创建 user Message，assistant round 的 parent_id 指向原 `task.input.user_message_id`。
- Produces: `recover_task_graph(...)`：后台任务同样以 failed checkpoint + `initial=None` 续跑。
- Contract: `chat_stream_events` 首次持久化 user Message 后，将 `user_message_id` 和 workspace id 写回 task.input；断点恢复用 `MessageRepository.max_round_for_parent` 计算 `round_offset`，不覆盖/复制旧工具轮。

- [ ] Step 1: 在 `tests/test_tasks_api.py` 写 `test_recover_rejects_nonrecoverable_nonfailed_and_exhausted_task`，分别断言 40902，且不会启动 graph。
- [ ] Step 2: 写 `test_concurrent_recover_with_same_or_different_keys_starts_once`，并发两次请求，断言 recovery_attempts 只增 1、运行表只有一个 producer；相同 key 返回当前状态而不重复执行。
- [ ] Step 3: 写 `test_resolve_execution_thread_prefers_chat_conversation_without_pending_confirm`，构造普通 chat failed Task，断言 thread 是 conversation id 而不是 task id。
- [ ] Step 4: 在 `tests/test_llm_transport_retry.py` 写 `test_manual_recover_rehydrates_chat_and_does_not_repeat_tool_side_effect`，首轮工具成功、模型两次断流后 failed；调用 recover 后成功，断言工具计数仍为 1、用户消息 1 条、assistant 工具轮 1 条、最终轮 1 条且 parent/round 正确。
- [ ] Step 5: 写 `test_manual_recover_rehydrates_attachment_and_workspace_file_context`，用 nonce 证明恢复请求重新读取当前附件/file_ref，但正文/base64 不落 checkpoint；缺失文件产生现有省略提示而不是重发用户消息。
- [ ] Step 6: 写 `test_recover_disconnect_keeps_background_graph_running_and_events_reconnectable`，客户端关闭 recover SSE 后图继续，`GET events?after_seq` 最终得到 done，Conversation reload 得到最终消息。
- [ ] Step 7: 运行 `pytest tests/test_tasks_api.py tests/test_llm_transport_retry.py tests/test_chat_stream.py -q`，预期 FAIL。
- [ ] Step 8: 实现 Task 字段、schema、CAS 和线程解析；首次 chat user message commit 后原子补写 task.input.user_message_id/workspace_id。
- [ ] Step 9: 抽取 chat `on_round_message/on_final/on_error` 的共用持久化 helper，供首次流、确认 resume 和 retry stream 复用；retry 不执行标题生成、附件回填或 user message create。
- [ ] Step 10: 实现 recover 路由、SSE/JSON 双轨和 task_worker 注册；取消仍通过同一 task_id 中断正在恢复的 producer。
- [ ] Step 11: 运行定向测试，预期 PASS；再运行 `pytest tests/test_chat_attachments.py tests/test_chat_file_refs.py tests/test_chat_document_context.py tests/test_cancel_inflight.py -q`。
- [ ] Step 12: 运行 `ruff check app/api/schemas/tasks.py app/api/routers/tasks.py app/services/task.py app/storage/models/task.py app/storage/repositories/task.py app/storage/repositories/message.py app/orchestration/chat_stream.py app/orchestration/task_run.py app/orchestration/task_worker.py tests/test_tasks_api.py tests/test_llm_transport_retry.py tests/test_chat_stream.py`。

---

## Task 7: 工具摘要统一有界，避免后续模型轮次膨胀

**Files:**
- Modify: `app/tools/executor.py`
- Modify: `app/orchestration/nodes/tool_execute.py`
- Test: `tests/test_executor_retry_idempotency.py`
- Test: `tests/test_agent_nodes.py`

**Interfaces:**
- Produces: `summarize_output(output: Any, limit_chars: int) -> OutputSummary`，其中 `OutputSummary` 字段为 `text/truncated/original_chars`。
- Compatibility: 保留 `_summarize(output: Any) -> str` 作为薄封装返回 `.text`，避免已有调用方一次性破坏。
- Contract: str/dict/list/其他可 JSON 序列化值都按 `tool_result_max_chars` 限制；截断尾部使用固定标记 `\n…[工具输出已截断，原始 N 字符]`，最终长度仍不得超过 limit。
- Contract: `ToolMessage.content` 和 LLM 后续上下文只使用 bounded summary；`ToolResult.output` 和前端 tool_result.output 保持现有完整值，不改变工具业务逻辑。
- Produces: tool result/state 增加 `summary_truncated`、`output_chars` 展示元数据；RunLog 只保存 bounded summary。

- [ ] Step 1: 将现有 `test_summarize_str_passthrough` 改为 `test_summarize_long_str_is_bounded_with_metadata`，断言长 str 不再全文进入模型、长度不超过 8000、truncated=true、original_chars 正确。
- [ ] Step 2: 参数化写 `test_summarize_output_bounds_dict_list_and_non_json_value`，覆盖 Unicode、多字节文本、非法 JSON 对象和 limit 小于标记长度的边界。
- [ ] Step 3: 在 `tests/test_agent_nodes.py` 写 `test_tool_message_uses_bounded_summary_but_result_keeps_full_output`，断言模型看到的 ToolMessage 不含尾部 nonce，tool_results.output 仍完整，metadata 指示截断。
- [ ] Step 4: 运行 `pytest tests/test_executor_retry_idempotency.py tests/test_agent_nodes.py -q`，预期 FAIL。
- [ ] Step 5: 实现 `OutputSummary` 和兼容 wrapper；修改 tool_execute 只在模型消息/run log 使用 `.text`，展示结果补 metadata。
- [ ] Step 6: 运行定向测试，预期 PASS；运行 `pytest tests/test_practical_tools.py tests/test_skill_injection.py tests/test_file_ops.py -q`，验证字符串工具和 load_skill 无回归。
- [ ] Step 7: 运行 `ruff check app/tools/executor.py app/orchestration/nodes/tool_execute.py tests/test_executor_retry_idempotency.py tests/test_agent_nodes.py`。

---

## Task 8: 前端交接契约与安全恢复 UX

**Files:**
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/progress.md`
- Frontend owner modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/api/sse.ts`
- Frontend owner modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/api/task-control.ts`
- Frontend owner modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/types/api.ts`
- Frontend owner modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/types/sse.ts`
- Frontend owner modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/composables/useChatStream.ts`
- Frontend owner modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/views/ChatView.vue`
- Frontend owner modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/workspace/WorkspaceShell.vue`
- Frontend owner modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/common/AgentRunStatus.vue`
- Frontend owner test: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/api/sse.spec.ts`
- Frontend owner test: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/composables/useChatStream.spec.ts`

**Interfaces:**
- Consumes: Task 4 的 `task_seq/after_seq/Last-Event-ID`，Task 5 的 `model_retry/reset_partial`，Task 6 的 Task.error 与 `/recover`。
- Handoff status: 在交接板顶部新增 `[open] 2026-08-29 · ←后端 | 长任务模型流断线恢复`；后端契约落地后追加 commit/test 结果，前端完成后由前端 Agent 改 `[done]`。
- Frontend state additions: `phase` 增加 `retrying|reconnecting|background_running|recoverable|disconnected`；每个 ConvCtx 保存 `taskCursor/reconnectAttempts/reconnectTimer/recoveryInFlight`。
- UX contract: transport error 且已有 task_id 时不得立即标记业务 failed、不得调用原 `start(req)`；先进入 reconnecting 并订阅 `/tasks/{id}/events?after_seq=cursor`。
- UX contract: `model_retry(reset_partial=true)` 只清当前未封口 partialText/thinking segment，保留已持久化 message/tool cards；显示“模型连接中断，正从最近断点重试（1/1）”。
- UX contract: `running/pending` 显示“任务仍在后台执行”；`waiting_confirm` 恢复确认弹窗；`done` reload messages/trajectory；`failed+recoverable` 显示“从断点继续”；其他 failed/cancelled 显示终态。
- UX contract: 自动重连 task events 最多 3 次，退避 300ms/600ms/1200ms 加 jitter；失败后进入 disconnected 并保留“重新连接”。
- UX contract: 当前“重试”按钮不得重新 POST 原 chat 请求；显式重新执行必须改名“重新执行（可能重复操作）”并与“从断点继续”分开，默认突出后者。

- [ ] Step 1: 在 `FrontEnd/progress.md` 交接板顶部写入上述 API 字段、状态机、禁止重发约束、测试矩阵和后端验收结果；保留现有未提交内容，不改写旧 done/open 条目。
- [ ] Step 2: 交接中要求前端先写 `SseTransportError(kind,status,traceId,lastSeq,hadEvents)` 测试，覆盖半截 body、首帧前断线和已有 task_id 后断线。
- [ ] Step 3: 交接中要求前端写普通 chat 对账测试：running 重连且不重复 POST、断线期间 done 后 reload、waiting_confirm 恢复弹窗、failed recoverable 调 `/recover`。
- [ ] Step 4: 交接中要求前端写 task_seq 去重测试：跨连接重复业务事件只应用一次；token 没有 task_seq 时只在当前连接消费，不写 cursor。
- [ ] Step 5: 交接中要求前端写 UI 测试：AgentRunStatus 展示 retrying/reconnecting/background/recoverable，ChatView 与 WorkspaceShell 均不再把危险重发作为默认“重试”。
- [ ] Step 6: 交接中列出前端门禁：`npm run typecheck`、`npm run test:unit`、`npm run lint:check`、`npm run build`；构建成功后由前端 Agent 同步生成物到后端 `frontend_dist`，后端不得直接手改压缩 bundle。
- [ ] Step 7: 后端执行者只更新交接板，不越权修改前端源码；前端 Agent 回写 done 与门禁结果后，再进行 Task 9 的真实联调。

---

## Task 9: 文档、全量门禁与真实断流验收

**Files:**
- Modify: `README.md`
- Modify: `docs/03-api-contracts.md`
- Modify: `progress.md`
- Verify: `frontend_dist/`（仅接收前端构建产物，不直接编辑）

**Interfaces:**
- Documents: `LLM_STREAM_CHUNK_TIMEOUT_S=300`、一次节点级自动重试、三次手动断点恢复上限、Task error schema、task event cursor 和 `/recover`。
- Documents: 明确“上下文窗口”和“流式空闲超时”是不同概念；系统没有把 unknown model 强制限制为 256K/1M。
- Runtime acceptance: health 端点确认新 backend 进程启动时间晚于本轮源码修改时间；不得再次由旧进程验证新代码。

- [ ] Step 1: 更新 README 配置和故障说明；更新 API 文档中 SSE envelope 的可选 `task_seq`、events cursor、model_retry、结构化 Task.error 和 recover 请求/响应示例。
- [ ] Step 2: 在 `progress.md` 记录每个 Task 状态、定向测试结果、真实验收 task/conversation id；不写 API key、请求正文或附件内容。
- [ ] Step 3: 运行定向总集：`pytest tests/test_llm.py tests/test_context_metrics.py tests/test_stream_core.py tests/test_json_file_saver.py tests/test_task_events.py tests/test_llm_transport_retry.py tests/test_tasks_api.py tests/test_chat_stream.py tests/test_interrupt_stream.py tests/test_executor_retry_idempotency.py -q`。
- [ ] Step 4: 运行相关回归：`pytest tests/test_cancel_inflight.py tests/test_graph_interrupt.py tests/test_chat_attachments.py tests/test_chat_file_refs.py tests/test_chat_document_context.py tests/test_notifications.py tests/test_skill_injection.py tests/test_file_ops.py -q`。
- [ ] Step 5: 运行全量 `pytest -q` 与 `ruff check app tests`；记录 passed/skipped 数量和任何既有 warning，不把失败测试误报为完成。
- [ ] Step 6: 使用 `review-test-simplify` 依次完成 Test gate、Review gate、Simplify gate；优先修复 P0/P1，P2/P3 发现记录到 progress 并由用户决定是否扩大范围。
- [ ] Step 7: 重启后端，调用 health 断言 `started_at` 晚于最新相关源码 mtime；使用 fake/proxy 故障注入复现“输出多个 chunk 后连接关闭”，验证自动重试事件、partial reset、工具只执行一次和最终 done。
- [ ] Step 8: 注入连续两次 transport failure，验证 Task 进入 failed+recoverable；点击“从断点继续”，验证同一 task/thread、无重复用户消息/工具副作用、event after_seq 补发和最终会话消息落库。
- [ ] Step 9: 用真实 `glm-5.3-flash` 运行一个包含 GitHub 查询和 DOCX 生成的长任务；若上游仍在约 180 秒关闭，验收系统能显示真实错误类别、attempt/chunk/idle/context metrics 并恢复，而不是误报上下文溢出。
- [ ] Step 10: 前端 Agent 完成 Task 8 后，运行其 typecheck/unit/lint/build 结果核对，并在真实 UI 验证顶部依次显示“模型重试/重新连接/后台执行/完成”且轨迹无重复工具卡。

---

## Explicit Non-Goals

- 本轮不实现历史上下文自动摘要、滑动窗口或强制 token 裁剪；观测数据稳定后另立计划按完整轮次压缩。
- 本轮不探测或维护“所有模型的 256K/1M 上下文名单”，不根据模型名称猜测窗口。
- 本轮不通过提高客户端 timeout 掩盖上游 180 秒主动断开；timeout 配置只是避免客户端 120 秒过早放弃。
- 本轮不自动重试工具节点，不尝试推断任意工具是否幂等。
- 本轮不持久化 token/thinking 流，也不承诺断线期间逐字补回；最终内容以 Conversation Message 为事实源。
- 本轮不直接编辑 `frontend_dist` 压缩产物；只接受前端源码构建生成的同步结果。
