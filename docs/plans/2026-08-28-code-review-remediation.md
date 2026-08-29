# Code Review Remediation Implementation Plan

**Goal:** 修复本分支代码审查发现的六项问题：跨轮图片引用泄漏、Task 二次中断线程丢失、Docker 输出无界缓冲、Docker Linux 写权限、激活 Provider 热同步滞后，以及非视觉图片重复计数；同时补齐 Docker 已声明但未落实的 `--pull never` 契约。
**Architecture:** 保持现有公开 API、数据模型和 LangGraph 状态机不变，在既有边界内做定点加固。多模态层通过显式空图片上下文触发历史引用净化；Task 恢复层持续使用首次解析出的 checkpoint 线程；Docker runner 用并发流式 drain、唯一容器名和平台用户解析加固宿主边界；Provider 服务把持久化配置与进程内 Settings 的同步收口到同一函数。
**Execution Workflow:** 实施时先用 `executor-debugger` 按本计划逐项执行并维护进度账本；所有行为变更测试先行。全部任务完成后，必须用 `review-test-simplify` 跑 Test / Review / Simplify 三道 gate，处理完发现后才允许提交。

**Execution Status (2026-08-28):** Tasks 1–5 implemented and verified. Test gate: targeted 193 passed, full suite 599 passed / 2 skipped; Ruff and diff checks pass. Review/Simplify found no Critical/High/Medium issues. Docker smoke is skipped because the current environment has no Docker CLI. Commit remains intentionally deferred pending explicit user approval.

**Global Constraints:** 本轮只处理上述审查项和与其直接相关的 `--pull never` 契约，不重构 LangGraph 状态机、不改变 SSE/REST 信封、不新增 Provider 字段、不扩充 Docker 镜像工具集。
**Global Constraints:** 图片 base64 仍只能存在于当前运行的 `configurable`；不得进入消息、checkpoint、Task 输入输出、事件、日志或持久化 Provider 数据。
**Global Constraints:** 首轮图片可以在该次 graph run 内正常水合；后续纯文本轮和 resume 必须把历史 `image_ref` 转成 `[图片已省略…]` 文本，绝不重放图片数据。
**Global Constraints:** `PreparedImageInput.omitted_count` 只表示视觉投递阶段的读盘失败或预算剔除；模型不支持图片由 `candidate_count` 单独表达。
**Global Constraints:** Task 二次中断继续复用同一个 Task 行；不得改成新建 Task，不得改变 `waiting_confirm -> running -> waiting_confirm/done` 状态语义。
**Global Constraints:** Docker stdout/stderr 必须持续排空以避免管道死锁，但宿主内存保留量必须有硬上限；最终返回仍保持 stdout 优先、stdout+stderr 合计不超过 `tool_result_max_chars` 字符。
**Global Constraints:** Docker 保持 `--network none`、只读根文件系统、唯一 workspace bind mount、capabilities 全删、no-new-privileges、不挂 Docker socket、不自动拉镜像且不回退宿主 shell。
**Global Constraints:** Linux 仅映射非 root 宿主 UID/GID；Windows、macOS、缺少 POSIX UID API 或宿主为 root 时继续回退 `65532:65532`，不得让容器以 root 运行。
**Global Constraints:** 不修改或覆盖 `~/.LiBao`、真实 `.env`、用户附件、工作区业务文件和无关未提交改动；Docker 集成测试只使用 pytest 临时目录。
**Global Constraints:** Provider 的 `api_key` 继续只写不读；inactive Provider 的普通 PATCH 不得改变当前运行时模型配置。
**Global Constraints:** 不顺带修改 `create(enabled=True)` 的多激活既有语义；该邻接问题另行规划，避免扩大本轮范围。
**Global Constraints:** 每项实现都先运行新增测试并确认因目标缺陷失败，再写最小实现；本轮所有实现文件在最终三道 gate 通过前不得提交。

---

## Design Decision

采用“现有边界内的最小兼容修复”，不选择以下三个更宽方案：

- 不把所有消息重写为新的持久化媒体模型；这会引入 checkpoint 迁移和历史数据兼容成本。现有 `image_ref -> render_message_content` 边界已经足够，只需保证每个聊天轮次都触发净化。
- 不新增常驻 Docker supervisor 或临时输出文件协议；并发流式读取可以在不改公开接口的情况下解决 OOM、死锁和清理问题。
- 不新增 Provider runtime manager；`ProviderService.sync_active_to_settings` 已是事实上的同步边界，应修正并复用它。

---

## Task 1: 净化跨轮图片引用并修正非视觉计数

**Files:**
- Modify: `app/orchestration/multimodal_input.py:20-103`
- Modify: `app/orchestration/chat_stream.py:74-105`
- Modify: `app/core/multimodal.py:70-112`（仅更新字段语义注释；消息函数签名不变）
- Test: `tests/test_multimodal.py`
- Test: `tests/test_chat_attachments.py`

**Interfaces:**
- Consumes: `PreparedImageInput(image_refs, image_payload, current_image_ids, candidate_count, omitted_count, vision)`。
- Preserves: `image_config(prepared: PreparedImageInput | None, *, force_context: bool = False) -> dict[str, Any]`。
- Produces: 当 `prepared is None and force_context=True` 时返回 `{"image_payload": {}, "current_image_ids": set(), "vision": False}`；当 `prepared` 非空时，即使 `force_context=True` 也必须保留它实际的 payload/current ids/vision。
- Produces: chat 每轮只要已经完成 `prepare_image_input`，就显式建立图片渲染上下文；无附件轮建立空上下文以净化历史引用。
- Preserves: Task 初次纯文本运行仍不新增图片 configurable 键；Task resume 继续显式空上下文。

- [ ] Step 1: 在 `tests/test_multimodal.py` 新增 `test_image_config_force_context_preserves_nonempty_prepared_payload`。构造一张 `ImagePayload` 和非空 `PreparedImageInput`，调用 `image_config(prepared, force_context=True)`，断言 payload 对象、`current_image_ids` 和 `vision=True` 原样保留，不能被 force 分支清空。
- [ ] Step 2: 在同文件新增 `test_image_config_force_context_emits_empty_keys_for_empty_prepared`。构造 `candidate_count=0` 的 `PreparedImageInput`，断言 force 后三个图片键都存在、payload/current ids 为空；再断言 `image_config(None, force_context=False) == {}`，保留真正无图片调用点的兼容路径。
- [ ] Step 3: 更新 `test_prepare_image_input_non_vision_never_reads_files`，把期望改为 `candidate_count == 1`、`omitted_count == 0`、无 refs/payload，并继续断言 `AttachmentService.read_file` 从未被调用。
- [ ] Step 4: 新增 `test_human_message_non_vision_does_not_duplicate_omission_count`：用 `refs=[]`, `vision=False`, `n_images=2`, `n_dropped=0` 构造消息，断言只出现“2 张图片已被忽略”，不包含“另有”“预算”或“读取失败”，且原始用户文本保持在结尾。
- [ ] Step 5: 在 `tests/test_chat_attachments.py` 新增集成回归 `test_image_then_plain_turn_degrades_historical_ref`。同一 conversation/checkpointer 首轮用视觉模型发送图片并完成，第二轮不带附件只发纯文本；断言第二次模型请求的所有 HumanMessage 块均无 `image_ref` 和 `image`，首轮历史位置包含“图片已省略”，第二轮用户文本逐字保持。
- [ ] Step 6: 运行 `uv run pytest tests/test_multimodal.py::test_image_config_force_context_preserves_nonempty_prepared_payload tests/test_multimodal.py::test_image_config_force_context_emits_empty_keys_for_empty_prepared tests/test_multimodal.py::test_prepare_image_input_non_vision_never_reads_files tests/test_multimodal.py::test_human_message_non_vision_does_not_duplicate_omission_count tests/test_chat_attachments.py::test_image_then_plain_turn_degrades_historical_ref -q`；预期至少 force-context、非视觉计数和跨轮集成测试 FAIL。
- [ ] Step 7: 重排 `image_config` 分支：先区分 `prepared is None`，再处理 `prepared`；force 只能要求“显式上下文”，不能抹掉非空 prepared。`chat_stream._graph_config` 在 `image_context is not None` 时调用 `image_config(image_context, force_context=True)`；Task 调用点保持现有参数。
- [ ] Step 8: 将非视觉 `PreparedImageInput.omitted_count` 改为 0，并同步 docstring/注释为“视觉投递失败数”；不改 `human_message_with_images` 的参数列表和视觉模型的预算/读盘失败计数。
- [ ] Step 9: 重跑 Step 6 命令，预期 PASS；再运行 `uv run pytest tests/test_multimodal.py tests/test_chat_attachments.py tests/test_tasks_api.py tests/test_interrupt_stream.py -q`，确认无图、视觉、非视觉、预算、resume 与 checkpoint 无 base64 回归全部通过。

---

## Task 2: 保留 Task 二次中断的原 checkpoint 线程

**Files:**
- Modify: `app/orchestration/task_run.py:54-99`
- Verify: `app/services/task.py:85-110,154-162`
- Verify: `app/api/routers/tasks.py:148-181`
- Test: `tests/test_interrupt_stream.py`

**Interfaces:**
- Preserves: `_run_graph_common(*, graph, task_id, initial, trace_id, model_override=None, image_context=None, force_image_context=False) -> None`。
- Consumes: `TaskService.resolve_resume_thread(task) -> str` 和原 `task.pending_confirm["conversation_id"]`。
- Produces: 每次 `on_interrupt` 写回同一个 resolved `thread_id`，保留原 `conversation_id`，只刷新 `node_id/value`、状态和 `created_at`。

- [ ] Step 1: 在 `tests/test_interrupt_stream.py` 新增 `test_json_resume_second_interrupt_preserves_original_thread`。使用能按顺序“首次工具确认 -> approved 后再次工具确认 -> 再次 approved 后最终答复”的测试模型：首次聊天中断创建 Task；第一次调用 `resume_task_graph(..., approved=True)` 后重读同一 Task，断言 `status == "waiting_confirm"`、`pending_confirm.thread_id == str(conversation.id)`、`pending_confirm.conversation_id == str(conversation.id)` 且 thread id 不等于 task id；第二次 resume 后断言 Task 进入 `done` 且未出现线程失效。
- [ ] Step 2: 运行 `uv run pytest tests/test_interrupt_stream.py::test_json_resume_second_interrupt_preserves_original_thread -q`；预期 FAIL，失败表现为 pending thread 被改写成 task id，或第二次 resume 找不到原 checkpoint。
- [ ] Step 3: 在 `_run_graph_common` 建立回调前捕获 `thread_id = TaskService.resolve_resume_thread(task)` 与 `conversation_id = (task.pending_confirm or {}).get("conversation_id")`；`on_interrupt` 写回这两个值，不再使用 `str(task.id)` 或无条件写 `None`。
- [ ] Step 4: 保持后台 `POST /tasks` 行为不变：其 resolved thread 本来就是 task id、conversation id 本来就是 None；保持 SSE resume 路径“二次中断新建 Task”的既有行为，不在本任务中合并两种状态机。
- [ ] Step 5: 重跑 Step 2，预期 PASS；再运行 `uv run pytest tests/test_interrupt_stream.py tests/test_tasks_api.py tests/test_graph_interrupt.py -q`，确认首次中断、批准、拒绝、TTL、JSON/SSE 双轨与 Task 事件回放无回归。

---

## Task 3: 将 Docker stdout/stderr 改为有界流式 drain

**Files:**
- Modify: `app/tools/sandbox.py:102-278`
- Modify: `tests/test_docker_sandbox.py`

**Interfaces:**
- Preserves: `run_docker_command(command: SandboxCommand, *, workspace_root: str, timeout_ms: int, settings: Any = None) -> SandboxResult`。
- Produces: `_read_stream_bounded(stream: asyncio.StreamReader, max_bytes: int) -> tuple[bytes, bool]`，持续读取到 EOF，只保留前 `max_bytes` 字节并返回是否丢弃过数据。
- Produces: `_communicate_bounded(process: asyncio.subprocess.Process, limit_chars: int) -> tuple[bytes, bytes, bool]`，并发 drain stdout/stderr 并等待进程结束；每流保留上限为 `max(4 * limit_chars, 65536)` 字节，最终仍交给 `_bound_output` 做合计字符裁切。
- Produces: `SandboxResult.truncated` 为流级丢弃或最终字符裁切的逻辑或。

- [ ] Step 1: 把 `tests/test_docker_sandbox.py` 的 fake process 改为暴露可异步 `read()` 的 stdout/stderr 与 `wait()`；令其 `communicate()` 直接抛 AssertionError，从测试层禁止 runner 回退到全量缓冲 API。
- [ ] Step 2: 新增 `test_large_stdout_and_stderr_are_drained_with_bounded_retention`：启动一个不经过 Docker 的 Python 子进程，让 stdout 和 stderr 各写至少 2 MiB，直接调用 `_communicate_bounded(process, limit_chars=1024)`；断言调用不死锁、两流都读到 EOF、保留字节量各不超过 65536，且 truncated=True。
- [ ] Step 3: 新增 `test_stream_reader_discards_after_limit_but_continues_to_eof`：用记录型 fake stream 分多块返回数据，断言 `_read_stream_bounded` 在超过上限后仍继续调用 `read()` 直到返回 `b""`，只保留指定前缀并标记截断。
- [ ] Step 4: 更新 `test_success_nonzero_and_output_are_bounded`，覆盖成功、普通非零退出和同时超量 stdout/stderr；断言最终 stdout+stderr 字符数不超过 `tool_result_max_chars`、stdout 优先规则不变，非零错误分类仍能从保留的 stderr 前缀识别。
- [ ] Step 5: 运行 `uv run pytest tests/test_docker_sandbox.py::test_large_stdout_and_stderr_are_drained_with_bounded_retention tests/test_docker_sandbox.py::test_stream_reader_discards_after_limit_but_continues_to_eof tests/test_docker_sandbox.py::test_success_nonzero_and_output_are_bounded -q`；预期 FAIL，因为当前 runner 使用 `process.communicate()`。
- [ ] Step 6: 实现两个私有 helper，把 `run_docker_command` 的 `wait_for(process.communicate())` 替换为 `wait_for(_communicate_bounded(...))`；保持现有超时错误码、Docker stderr 分类和最终 `_bound_output` 规则。
- [ ] Step 7: 重跑 Step 5，预期 PASS；运行 `uv run pytest tests/test_docker_sandbox.py tests/test_executor_retry_idempotency.py tests/test_file_ops.py -q`，确认 executor 重试、超时、非零退出和语义审查结果映射无回归。

---

## Task 4: 消除 Docker 清理竞态并修正运行用户/拉取策略

**Files:**
- Modify: `app/tools/sandbox.py:118-278`
- Modify: `tests/test_docker_sandbox.py`
- Modify: `README.md:46-62`

**Interfaces:**
- Produces: `_runtime_user() -> str`；仅 Linux 且 `os.getuid()`/`os.getgid()` 都大于 0 时返回 `"<uid>:<gid>"`，其他环境返回 `"65532:65532"`。
- Changes private interface: `_docker_argv(command, workspace_root, cidfile, container_name, settings) -> tuple[str, ...]`，新增唯一容器名并包含 `--name <name>`、`--pull never`。
- Changes private interface: `_force_remove(container_ref: str, settings: Any) -> None` 可接收 cid 或唯一容器名；自身超时必须 kill/wait cleanup CLI，不得覆盖原失败。
- Preserves: Dockerfile 的 `USER 65532:65532` 作为安全回退；不修改镜像包集。

- [ ] Step 1: 更新 `test_docker_argv_has_security_defaults` 为 `test_docker_argv_has_security_defaults_and_never_pulls`，除现有安全参数外断言 `--pull` 后紧跟 `never`，`--name` 值以 `libao-sandbox-` 开头且本次调用唯一。
- [ ] Step 2: 新增 `test_docker_argv_maps_non_root_linux_uid_gid`，monkeypatch `sys.platform="linux"`, `os.getuid=lambda:1000`, `os.getgid=lambda:1001`，断言 `--user 1000:1001`。
- [ ] Step 3: 新增 `test_docker_argv_falls_back_to_65532_without_linux_ids` 和 `test_docker_argv_falls_back_to_65532_for_root`，分别覆盖 Windows/macOS/无 UID API 与 uid/gid 任一为 0，断言绝不产生 `--user 0:0`。
- [ ] Step 4: 新增 `test_timeout_removes_named_container_when_cidfile_is_still_empty` 和 `test_cancellation_removes_named_container_when_cidfile_is_still_empty`：模拟 Docker CLI 已启动但 cidfile 尚未写入，断言 cleanup 仍对唯一 container name 执行 `docker rm -f`，原 timeout/CancelledError 语义不变。
- [ ] Step 5: 新增 `test_stream_read_failure_kills_cli_and_force_removes_container` 与 `test_force_remove_timeout_kills_cleanup_process_without_masking_original_error`。reader 抛 `OSError` 时断言 Docker CLI 被 kill/wait、容器被 force remove，最终得到 `SandboxFailure(code=START_FAILED, retryable=True)` 且保留原异常为 `__cause__`；cleanup 自身超时时断言不会覆盖原 `SandboxFailure(TIMEOUT)` 或 `CancelledError`。
- [ ] Step 6: 运行 `uv run pytest tests/test_docker_sandbox.py -q`；预期新增 UID、pull、named cleanup 和异常清理测试 FAIL。
- [ ] Step 7: 新增唯一 container name，Docker argv 加 `--pull never`；超时、取消和流读取异常统一执行“kill/wait Docker CLI -> cid 若存在否则 name -> shield 后的限时 force remove”，cleanup 错误仅记录日志。流读取异常完成清理后转换为 retryable `SandboxFailure(START_FAILED)` 并用异常链保留根因。
- [ ] Step 8: 实现 `_runtime_user` 并替换固定 `65532:65532`；保留所有既有隔离参数，不把 UID/GID 暴露为 API 或 Settings 配置。
- [ ] Step 9: 更新 README，明确“不自动 pull”由 `--pull never` 强制；Linux 非 root 映射宿主 UID/GID以保证 bind-mounted workspace 可写，其他环境回退 65532；最小镜像仍只保证 bash、Python、Git、ripgrep、findutils。
- [ ] Step 10: 重跑 Step 6，预期 PASS。Docker 和固定镜像可用时，再运行一个带显式 skip 条件的 smoke：在 pytest 临时 workspace 中执行 `python --version`, `git --version`, `rg --version`, `find --version`, `touch probe`，断言 probe 可见、Linux owner UID 等于宿主 UID，且测试后不存在该唯一 name/label 的容器；Docker 或镜像不可用时记录为 SKIP，不得自动 pull。

---

## Task 5: 统一激活 Provider 的运行时热同步与回退

**Files:**
- Modify: `app/services/provider.py:13-119`
- Test: `tests/test_provider.py`
- Verify: `app/api/routers/settings.py:20-103`
- Verify: `app/core/config.py:88-107`

**Interfaces:**
- Preserves: `ProviderService.patch`, `activate`, `delete`, `sync_active_to_settings` 的公开签名和路由响应。
- Consumes: `Settings()` 作为未受 Provider 覆盖的配置基线；`get_settings()` 作为当前进程运行时单例。
- Produces: `sync_active_to_settings` 每次先把 runtime 的 `llm_model`, `llm_base_url`, `llm_api_key`, `llm_vision_declared` 恢复为基线，再用当前激活 Provider 的非空 model/base/key 覆盖；capabilities 继续遵守 `vision -> True`、非空且不含 vision -> False、空 -> None。
- Produces: active Provider 的普通 PATCH、停用和删除在持久化后立即同步；inactive Provider 的普通 PATCH 不同步。

- [ ] Step 1: 在 `tests/test_provider.py` 新增 `test_provider_patch_active_fields_hot_syncs_without_reactivation`：建立唯一 active Provider，不传 enabled，PATCH model/base_url/is_full_url/api_key/capabilities=["text-only"]；断言持久化字段和 runtime 四字段立即更新，`llm_vision_declared is False`；再 PATCH capabilities=[]，断言 vision declaration 变为 None。
- [ ] Step 2: 新增 `test_provider_patch_inactive_fields_does_not_change_runtime_settings`：修改 inactive Provider 的 model/capabilities，断言当前 runtime model/base/key/vision 完全不变。
- [ ] Step 3: 新增 `test_provider_deactivate_active_restores_base_settings` 和 `test_provider_delete_active_restores_base_settings`。monkeypatch `app.services.provider.Settings` 返回固定 fallback `fallback-model`, `https://fallback.example/v1`, `fallback-key`；分别 PATCH enabled=False 和删除 active 行，断言 runtime 恢复这三个 fallback 值且 `llm_vision_declared is None`。
- [ ] Step 4: 新增 `test_provider_clear_active_fields_uses_base_settings`：对 active 行 PATCH model/base_url/api_key 为 None，断言这些 runtime 字段回退到固定 baseline，而不是残留旧 Provider 值；序列化响应仍不含 api_key。
- [ ] Step 5: 运行 `uv run pytest tests/test_provider.py::test_provider_patch_active_fields_hot_syncs_without_reactivation tests/test_provider.py::test_provider_patch_inactive_fields_does_not_change_runtime_settings tests/test_provider.py::test_provider_deactivate_active_restores_base_settings tests/test_provider.py::test_provider_delete_active_restores_base_settings tests/test_provider.py::test_provider_clear_active_fields_uses_base_settings -q`；预期除 inactive 测试外均 FAIL。
- [ ] Step 6: `patch` 在改字段前记录 `was_active = bool(row.enabled)`；`enabled=True` 继续委托 `activate`；其他字段 commit/refresh 后仅当 `was_active` 时调用 `sync_active_to_settings`。`delete` 同样只在删除前 active 时于 commit 后同步。
- [ ] Step 7: 修改 `sync_active_to_settings`：构造一次 `baseline = Settings()`，先无条件恢复 model/base/key/vision，再读取 active Provider 并用其非空字段覆盖；不返回或记录明文 key，不改变 capabilities 三态推导。
- [ ] Step 8: 重跑 Step 5，预期 PASS；再运行 `uv run pytest tests/test_provider.py tests/test_multimodal.py tests/test_llm.py tests/test_chat_stream.py -q`，确认模型选择、视觉判定、DeepSeek thinking 和 key 只写不读契约无回归。

---

## Task 6: 全量验证、审查、简化与单次提交

**Files:**
- Verify: all files changed by Tasks 1-5
- Update only if required by verified behavior: `progress.md`

**Interfaces:**
- Consumes: Tasks 1-5 的全部测试和实现。
- Produces: 一个通过 Test / Review / Simplify gates、无占位项、无无关改动的可提交变更集。

- [ ] Step 1: 运行定点套件：`uv run pytest tests/test_multimodal.py tests/test_chat_attachments.py tests/test_interrupt_stream.py tests/test_tasks_api.py tests/test_graph_interrupt.py tests/test_docker_sandbox.py tests/test_executor_retry_idempotency.py tests/test_file_ops.py tests/test_provider.py tests/test_llm.py tests/test_chat_stream.py -q`，预期全部 PASS；Docker smoke 允许因 daemon/镜像缺失明确 SKIP，其余不得 skip 新行为测试。
- [ ] Step 2: 运行完整测试：`uv run pytest tests/ -q`，预期零失败；记录既有 deprecation warning，但不得把 warning 当作本轮失败修复范围扩张。
- [ ] Step 3: 运行静态检查：`uv run ruff check app tests`、`git diff --check`，预期均通过。
- [ ] Step 4: 运行不变量搜索：`rg -n "process\.communicate\(\)|\"image_ref\"|thread_id.*task\.id|65532:65532|--pull" app tests README.md`。逐项确认：Docker 主执行路径不再 communicate；`image_ref` 只存在于内部构造/测试且所有模型出站路径会净化；Task interrupt 不再硬写 task id；65532 只作为安全回退；Docker argv 明确包含 `--pull never`。
- [ ] Step 5: 按仓库约定调用 `review-test-simplify`，依次完成 Test gate、Review gate、Simplify gate；对 Critical/High/Medium 发现先修复并重跑相应测试，对 Low 发现记录后由用户决定是否纳入。
- [ ] Step 6: 检查 `git status --short` 和 `git diff --stat`，确认只包含本计划授权的实现、测试和文档；不得覆盖用户原有改动。
- [ ] Step 7: 仅在三道 gate 全部通过且用户批准后提交一次 Conventional Commit：`fix(agent): harden multimodal recovery and sandbox runtime`。提交前运行 `git diff --cached --check`，提交后回报 commit id、完整测试结果与 Docker smoke 的 PASS/SKIP 状态。

---

## Requirement Coverage

| 审查项 | 计划任务 | 验证锚点 |
|---|---|---|
| 历史 `image_ref` 在纯文本下一轮泄漏 | Task 1 | `test_image_then_plain_turn_degrades_historical_ref` |
| Task 二次中断改写 checkpoint thread | Task 2 | `test_json_resume_second_interrupt_preserves_original_thread` |
| Docker 输出先全量缓冲再截断 | Task 3 | 大 stdout/stderr 并发 drain 测试 |
| Docker 固定 UID 导致 Linux workspace 不可写 | Task 4 | UID/GID argv 单测 + gated rw smoke |
| Docker 声称不拉取但缺少 `--pull never` | Task 4 | argv 契约测试 |
| active Provider PATCH/停用/删除后 runtime 陈旧 | Task 5 | active/inactive/deactivate/delete/clear 五组测试 |
| 非视觉图片被重复计数 | Task 1 | 非视觉 prepare + 消息文本断言 |
