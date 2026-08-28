# Task API, Docker Sandbox, and Task Multimodal Implementation Plan

**Goal:** Close the confirmed gaps in item 1 (broken Task API runtime wiring), item 2 (Docker isolation for `tl_bash`), and item 4 (attachments and image multimodality for background Tasks), while explicitly leaving item 3 (Webhook) out of scope.
**Architecture:** Finish the file-storage migration by removing the obsolete `sessionmaker` parameter chain instead of recreating a fake application state field. Implement Docker isolation as a command-runner boundary used only by `tl_bash`: semantic review and workspace validation build a typed command, and a one-shot locked-down container executes it. Reuse one owner-aware multimodal preparation layer for chat and Task paths so base64 stays in LangGraph `configurable`, checkpoints keep only lightweight image references, and resume always degrades references to text rather than replaying media.
**Global Constraints:** Item 3 / Webhook is explicitly excluded: do not create, restore, document, or register hooks/webhook routes, models, services, or tests.
**Global Constraints:** Preserve the public Task envelope `{"input": {...}, "params": ...}` and keep `input` backward compatible with arbitrary extra keys; only optional `message` and `attachment_ids` receive new validation and normalization.
**Global Constraints:** Docker scope is `tl_bash` only; do not serialize arbitrary Python handlers into containers and do not implement `microvm`.
**Global Constraints:** Docker networking is always `none`; do not interpret the existing tool `allowlist` as a network allowlist and do not mount the Docker socket, user home, `.env`, `~/.LiBao`, or application data.
**Global Constraints:** Docker execution never automatically pulls an image and never silently falls back to host-shell execution when the image or daemon is unavailable.
**Global Constraints:** The only host bind mount is the resolved current workspace root at `/workspace`; model input may select only a validated relative `cwd` below that root.
**Global Constraints:** Image base64 must never enter `Task.input`, `Task.output`, `Task.error`, SSE/event payloads, run logs, LangGraph state/messages, or checkpoint files.
**Global Constraints:** Preserve byte-identical behavior for plain chat and Task inputs with no attachments.
**Global Constraints:** Preserve existing user files and configuration under `~/.LiBao`; tests must use temporary FileStore roots and mocked Docker processes unless marked optional integration tests.
**Global Constraints:** Use TDD for every behavior change and finish with the repository `review-test-simplify` Test/Review/Simplify gates before any commit.

---

## Task 1: Remove the obsolete Task `sessionmaker` chain and cover the real HTTP entry points

**Files:**
- Modify: `app/api/routers/tasks.py:77-180`
- Modify: `app/orchestration/task_worker.py:27-61`
- Modify: `app/orchestration/task_run.py:53-234`
- Modify: `app/storage/file/store.py:108-116`
- Modify: `tests/test_tasks_api.py`
- Modify: `tests/test_cancel_inflight.py`
- Modify: `tests/test_placeholder_timeout.py`
- Modify: `tests/conftest.py:14-22`

**Interfaces:**
- Consumes: FastAPI lifespan state containing only `store`, `checkpointer`, and `graph`; `FileStore.session()` as the sole storage-session factory.
- Produces: `spawn_run(*, graph: Any, task_id: uuid.UUID, trace_id: str, approved: bool | None = None, model_override: Any = None) -> asyncio.Task` with no ORM/session factory parameter.
- Produces: `run_task_graph(*, graph: Any, task_id: uuid.UUID, trace_id: str, model_override: Any = None) -> None` and `resume_task_graph(*, graph: Any, task_id: uuid.UUID, approved: bool, trace_id: str, model_override: Any = None) -> None` that open `get_store().session()` directly.
- Produces: `FileStore.session(self) -> AsyncIterator[FileContext]` with the dead compatibility parameter removed.

- [ ] Step 1: Add async route regression `test_post_tasks_spawns_run_without_sessionmaker_app_state` in `tests/test_tasks_api.py`; create an app/request state with `graph` and no `sessionmaker`, monkeypatch `spawn_run`, call the real `POST /api/v1/tasks`, and assert HTTP 200, a valid returned `task_id`, a persisted Task, and captured kwargs exactly `{graph, task_id, trace_id}`. Run this test and expect the current route to fail with HTTP 500 / missing `app.state.sessionmaker` after Task persistence.
- [ ] Step 2: Add async route regression `test_json_resume_spawns_run_without_sessionmaker_app_state`; prepare a `waiting_confirm` Task and fake graph snapshot, call `POST /api/v1/tasks/{id}/resume` with `Accept: application/json` and `approved=true`, and assert HTTP 200 plus captured kwargs `{graph, task_id, approved=True, trace_id}` with no `sessionmaker` key. Run it and expect FAIL on the same missing state attribute.
- [ ] Step 3: Add `test_json_resume_denied_preserves_false_approved`; submit `approved=false`, assert `spawn_run` receives `approved is False` rather than `None`, and assert no `sessionmaker` argument. Run it and expect FAIL before the route fix.
- [ ] Step 4: Remove both `request.app.state.sessionmaker` reads from `app/api/routers/tasks.py`; do not add `app.state.sessionmaker = None` in `main.py`.
- [ ] Step 5: Remove `sessionmaker` from `spawn_run`, `_run_graph_common`, `_mark_failed`, `run_task_graph`, and `resume_task_graph`; replace every `get_store().session(sessionmaker)` with `get_store().session()` and update the worker forwarding calls.
- [ ] Step 6: Remove the ignored argument from `FileStore.session`; update direct calls in `tests/test_tasks_api.py`, `tests/test_cancel_inflight.py`, and `tests/test_placeholder_timeout.py`, and remove the stale `sql_sessionmaker` comment from `tests/conftest.py`.
- [ ] Step 7: Run `rg -n "state\.sessionmaker|sessionmaker=|session\(sessionmaker\)" app tests`; expect no Task/FileStore compatibility references.
- [ ] Step 8: Run `tests/test_tasks_api.py tests/test_cancel_inflight.py tests/test_placeholder_timeout.py`; expect all route, runner, cancellation, resume, and placeholder assertions to pass.
- [ ] Step 9: Commit only Task 1 files with message `fix(tasks): remove stale sessionmaker runtime wiring` after checking `git diff --cached --check`.

---

## Task 2: Define the Docker command sandbox contract and strict configuration boundary

**Files:**
- Modify: `app/tools/sandbox.py`
- Modify: `app/tools/registry.py:27-48`
- Modify: `app/core/config.py`
- Modify: `app/api/schemas/tools.py:9-34`
- Modify: `app/services/tool.py:55-108`
- Create: `tests/test_docker_sandbox.py`
- Modify: `tests/test_tool_service.py`

**Interfaces:**
- Produces: `SandboxCommand(argv: tuple[str, ...], workdir: str = "/workspace", workspace_access: Literal["ro", "rw"] = "rw", env: Mapping[str, str] = {})` containing container-internal values only.
- Produces: `SandboxResult(exit_code: int, stdout: str, stderr: str, timed_out: bool = False, truncated: bool = False)`.
- Produces: `SandboxFailure(code: SandboxErrorCode, message: str, retryable: bool = False, output: dict[str, Any] | None = None)` as a typed exception caught only at the executor boundary.
- Produces: `ToolSpec.sandbox_command_builder: Callable[..., SandboxCommand | Awaitable[SandboxCommand]] | None = None`; `sandbox=DOCKER` requires this field and `sandbox=NONE` continues to require `handler`.
- Consumes: settings `sandbox_docker_cli="docker"`, `sandbox_docker_image="libao-sandbox:py312-v1"`, `sandbox_docker_memory="512m"`, `sandbox_docker_cpus="1"`, `sandbox_docker_pids_limit=128`, and `sandbox_docker_tmpfs_mb=64`.

- [ ] Step 1: In new `tests/test_docker_sandbox.py`, add contract tests `test_sandbox_command_rejects_host_absolute_workdir`, `test_sandbox_command_rejects_parent_escape`, and `test_sandbox_command_accepts_workspace_relative_workdir`; assert Windows drive paths, POSIX absolute paths outside `/workspace`, and `..` traversal are rejected before any process call.
- [ ] Step 2: Add schema tests in `tests/test_tool_service.py` proving `CreateToolRequest`/`UpdateToolRequest` accept only `none`, `docker`, or `microvm`, reject timeout below 1 ms, reject concurrency below 1, and convert persisted strings to `SandboxLevel` when syncing a `ToolSpec`.
- [ ] Step 3: Run the new contract/schema tests and expect FAIL because `SandboxCommand`, strict enums, and numeric bounds do not exist.
- [ ] Step 4: Replace the callable-oriented `run_in_sandbox` stub with the immutable command/result/failure contracts and `SandboxErrorCode` values `sandbox_unavailable`, `sandbox_image_missing`, `sandbox_invalid_workdir`, `sandbox_unsupported_tool`, `sandbox_start_failed`, `sandbox_timeout`, and `sandbox_exit_nonzero`; keep `SandboxLevel.MICROVM` as a validated but explicitly unsupported level.
- [ ] Step 5: Add `sandbox_command_builder` to `ToolSpec`; preserve it through `replace()`-based registry synchronization and ensure it is a runtime-only field that is never serialized to API responses or FileStore rows.
- [ ] Step 6: Add the six Docker settings to `Settings`; validate positive CPU/memory/pid/tmpfs values without probing Docker during settings construction.
- [ ] Step 7: Change tool request schemas to `SandboxLevel` fields with `Field` bounds for `timeout_ms` and `max_concurrency`; in `ToolService`, convert persisted strings to `SandboxLevel` and reject unknown legacy values with a parameter error instead of installing a malformed runtime spec.
- [ ] Step 8: Run `tests/test_docker_sandbox.py tests/test_tool_service.py tests/test_tools.py`; expect PASS and no execution behavior changes yet.
- [ ] Step 9: Commit Task 2 files with message `feat(sandbox): define docker command contracts`.

---

## Task 3: Implement a one-shot locked-down Docker CLI runner

**Files:**
- Modify: `app/tools/sandbox.py`
- Create: `docker/sandbox/Dockerfile`
- Create: `scripts/build_sandbox.cmd`
- Create: `scripts/build_sandbox.sh`
- Modify: `tests/test_docker_sandbox.py`
- Modify: `.dockerignore`

**Interfaces:**
- Produces: `run_docker_command(command: SandboxCommand, *, workspace_root: str, timeout_ms: int, settings: Settings | None = None) -> SandboxResult`.
- Consumes: a host workspace root supplied only from `TOOL_WORKSPACE_ROOT`, resolved before process creation; a command whose workdir is `/workspace` or a descendant.
- Produces: one `docker run --rm` process per invocation, with container ID recorded through a temporary `--cidfile` and force-removed on timeout or cancellation.

- [ ] Step 1: Add mocked process test `test_docker_argv_has_security_defaults`; capture argv and assert it contains `--network none`, `--memory 512m`, `--cpus 1`, `--pids-limit 128`, `--read-only`, `--tmpfs /tmp:rw,noexec,nosuid,size=64m`, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--user 65532:65532`, and `--label libao.sandbox=true`.
- [ ] Step 2: Add `test_windows_workspace_is_the_only_bind_mount`; pass a Windows workspace path containing spaces, assert it remains one argv element, target is exactly `/workspace`, requested access is `rw` or `ro`, and no argv contains `.env`, `.LiBao`, `/var/run/docker.sock`, or a second `--mount`.
- [ ] Step 3: Add `test_relative_cwd_maps_under_container_workspace`; assert host-relative `src/tools` maps to container `/workspace/src/tools` and no host path appears in `--workdir`.
- [ ] Step 4: Add `test_invalid_workspace_or_cwd_does_not_start_docker`; cover nonexistent workspace, host-absolute `cwd`, and parent traversal, asserting `sandbox_invalid_workdir` and zero subprocess calls.
- [ ] Step 5: Add `test_missing_image_returns_stable_failure_without_pull` and `test_daemon_unavailable_returns_stable_failure`; mock Docker stderr, assert codes `sandbox_image_missing` / `sandbox_unavailable`, and assert no `docker pull` invocation.
- [ ] Step 6: Add `test_timeout_force_removes_cidfile_container`; simulate timeout after writing a container ID, assert `docker rm -f <id>` is invoked, the cidfile is removed, and `sandbox_timeout.retryable is False`.
- [ ] Step 7: Add `test_cancellation_cleans_container_and_reraises`; cancel the runner, assert forced removal occurs and `asyncio.CancelledError` propagates rather than becoming a `SandboxFailure`.
- [ ] Step 8: Add success/nonzero/output tests: success returns exit 0 and bounded stdout/stderr; nonzero produces `sandbox_exit_nonzero` with exit code and bounded streams; oversized combined output sets `truncated=True` and never exceeds `tool_result_max_chars`.
- [ ] Step 9: Implement Docker CLI invocation exclusively with `asyncio.create_subprocess_exec(*argv)` and temporary cidfile creation; never use `shell=True`, an interpolated Docker command string, or unresolved model-provided mount paths.
- [ ] Step 10: Create `docker/sandbox/Dockerfile` from `python:3.12-slim`, install only `bash`, `git`, `ripgrep`, and `findutils`, remove apt indexes, set `/workspace` as workdir, and declare numeric user `65532:65532`; create Windows and POSIX build scripts that run `docker build -t libao-sandbox:py312-v1 -f docker/sandbox/Dockerfile docker/sandbox`.
- [ ] Step 11: Run all mocked Docker tests on a machine without requiring Docker; when Docker Desktop is available, run optional integration checks that workspace writes are visible, `/etc` is container-local, outbound network fails, and no `libao.sandbox=true` container remains after timeout.
- [ ] Step 12: Commit Task 3 files with message `feat(sandbox): add locked-down docker runner`.

---

## Task 4: Route `tl_bash` through Docker while preserving semantic review and confirmation order

**Files:**
- Modify: `app/tools/builtin/file_ops.py:568-641`
- Modify: `app/tools/builtin/__init__.py:595-617`
- Modify: `app/tools/executor.py:108-190`
- Modify: `app/seed.py`
- Modify: `tests/test_executor_retry_idempotency.py`
- Modify: `tests/test_file_ops.py`
- Modify: `tests/test_graph_interrupt.py`
- Modify: `tests/test_seed_local.py`

**Interfaces:**
- Produces: `build_bash_sandbox_command(command: str, cwd: str | None = None) -> SandboxCommand` as an async builder that executes `_fast_review` / `_review_command`, reads workspace root only from `get_tool_workspace_root()`, validates `cwd` with `resolve_workspace_path`, and returns `argv=("bash", "-lc", command)` with a container-only workdir.
- Consumes: `ToolSpec.timeout_ms` as the single deadline for semantic review, command preparation, Docker startup, execution, and cleanup.
- Produces: `executor.execute` dispatch rules: `NONE -> handler`, `DOCKER -> sandbox_command_builder + run_docker_command`, `MICROVM -> sandbox_unsupported_tool`; only typed retryable Docker start failures participate in `max_retries`.

- [ ] Step 1: Replace the old “Docker always rejected” test with `test_docker_requires_command_builder`, `test_docker_runner_receives_workspace_and_spec_timeout`, and `test_microvm_remains_unsupported`; run and expect FAIL against the guard in `executor.execute`.
- [ ] Step 2: Add retry tests proving `sandbox_timeout`, policy rejection, invalid workdir, image missing, and nonzero command exit are not retried; `sandbox_start_failed` / `sandbox_unavailable` respect `max_retries`; and only successful Docker results enter the idempotency cache.
- [ ] Step 3: Add file-ops tests `test_bash_builder_uses_bash_lc`, `test_bash_builder_never_embeds_host_workspace_path`, `test_bash_review_block_prevents_docker_start`, `test_bash_cwd_escape_prevents_docker_start`, and `test_bash_has_no_legacy_120_second_timeout`; assert review rejection and path rejection occur before the Docker runner is called.
- [ ] Step 4: Add graph confirmation tests `test_docker_tool_denied_creates_no_container` and `test_docker_tool_approved_creates_exactly_one_container`; preserve the existing `tool_execute_node` order so interrupt approval happens before image probing or process creation.
- [ ] Step 5: Split `bash_handler` into policy/command preparation and host execution only for explicitly `sandbox=NONE` test/custom specs; register built-in `tl_bash` with `sandbox=SandboxLevel.DOCKER`, `sandbox_command_builder=build_bash_sandbox_command`, and no host handler fallback.
- [ ] Step 6: Refactor executor dispatch under the existing idempotency and semaphore boundaries; apply `asyncio.wait_for` once around the complete attempt, map `SandboxFailure` to `ToolResult(ok=False, output=failure.output, error=f"{code}: {message}")`, re-raise cancellation, and cache only `ok=True` results.
- [ ] Step 7: Remove the hard-coded `subprocess.run(... timeout=120)` path from built-in `tl_bash`; preserve readable stdout/stderr/return-code hints in Docker result mapping and preserve the existing semantic-review degraded note when review fail-open permits execution.
- [ ] Step 8: Update seed upgrade behavior so existing built-in `tl_bash` rows are set to `sandbox="docker"`; do not change custom tools named differently and do not enable any disabled tool.
- [ ] Step 9: Run executor, file-ops, graph interrupt, seed, and Docker suites; then run a manual Docker smoke through `executor.execute(get("tl_bash"), {"command": "pwd && touch sandbox-ok"})` in a temporary workspace and verify the file appears only inside that workspace.
- [ ] Step 10: Commit Task 4 files with message `feat(tools): isolate bash execution in docker`.

---

## Task 5: Validate Task attachment input without breaking arbitrary Task payloads

**Files:**
- Modify: `app/api/schemas/tasks.py`
- Modify: `app/api/routers/tasks.py:77-96`
- Modify: `app/services/attachment.py:52-67`
- Modify: `tests/test_tasks_api.py`

**Interfaces:**
- Consumes: existing request shape `SubmitTaskRequest(input: dict[str, Any], params: dict[str, Any] | None)`.
- Produces: normalized `Task.input` where optional `message` is a string no longer than `CONTENT_LIMIT`, optional `attachment_ids` is a list of canonical UUID strings, and every unrelated key/value is preserved unchanged.
- Produces: `AttachmentService.get_owned_many(db: Any, user_id: uuid.UUID, attachment_ids: list[uuid.UUID]) -> list[Attachment]` preserving request order and raising `ERR_ATTACHMENT_NOT_FOUND` if any row is absent, deleted, or owned by another user.

- [ ] Step 1: Add schema tests `test_submit_task_preserves_extra_input_keys`, `test_submit_task_normalizes_attachment_uuid_strings`, `test_submit_task_rejects_non_list_attachment_ids_422`, `test_submit_task_rejects_invalid_attachment_uuid_422`, and `test_submit_task_rejects_overlong_message`; assert arbitrary legacy payload keys survive model validation byte-for-byte at the Python-value level.
- [ ] Step 2: Add route tests `test_submit_task_rejects_foreign_attachment_before_task_creation` and `test_submit_task_rejects_deleted_attachment_before_task_creation`; assert error code 40403, Task count unchanged, and `spawn_run` not called.
- [ ] Step 3: Run the new tests and expect FAIL because Task input is not normalized and the route creates a Task without attachment checks.
- [ ] Step 4: Add a `field_validator("input")` that copies the incoming dict, validates only `message` and `attachment_ids`, canonicalizes UUIDs to strings, uses `Field(default_factory=dict)` / `Field(default_factory=list)` instead of mutable defaults, and leaves all other values untouched.
- [ ] Step 5: Add the ordered owner-aware batch service helper; use `AttachmentRepository.get(user_id, id)` rather than `get_any_org`, stop on the first inaccessible attachment, and perform no disk reads during submission.
- [ ] Step 6: In `submit_task`, validate all attachment IDs before `TaskService.submit` and before `spawn_run`; persist `req.input` after normalization. Keep `params` behavior unchanged.
- [ ] Step 7: Run Task schema/route tests plus `tests/test_attachments_api.py`; expect PASS and unchanged plain Task behavior.
- [ ] Step 8: Commit Task 5 files with message `feat(tasks): validate optional attachment input`.

---

## Task 6: Extract one owner-aware multimodal preparation pipeline for chat and Tasks

**Files:**
- Create: `app/orchestration/multimodal_input.py`
- Modify: `app/orchestration/chat_stream.py:78-166`
- Modify: `app/api/routers/chat.py:81-105`
- Modify: `app/core/multimodal.py`
- Modify: `app/orchestration/stream_core.py:127-205`
- Modify: `app/orchestration/nodes/agent_execute.py:27-42`
- Modify: `tests/test_multimodal.py`
- Modify: `tests/test_chat_attachments.py`

**Interfaces:**
- Produces: immutable `PreparedImageInput(image_refs: tuple[dict[str, str], ...], image_payload: dict[str, ImagePayload], current_image_ids: frozenset[str], candidate_count: int, omitted_count: int, vision: bool)`.
- Produces: `prepare_image_input(db: Any, *, user_id: uuid.UUID, attachment_ids: list[str], effective_model: str) -> PreparedImageInput`; owner validation uses `AttachmentRepository.get`, non-image MIME is ignored, non-vision models never read image files, and image order follows the request.
- Produces: `image_config(prepared: PreparedImageInput | None, *, force_context: bool = False) -> dict[str, Any]`; when forced, it emits explicit empty `image_payload`, `current_image_ids`, and `vision=False` keys so historical references downgrade on resume.
- Produces: `build_initial_state(..., image_refs: list[dict[str, str]] | None = None, image_candidate_count: int = 0, image_omitted_count: int = 0)` and `human_message_with_images(..., n_images: int = 0, n_dropped: int = 0)`.

- [ ] Step 1: Add preparation tests proving owner-aware lookup, request-order preservation, image MIME filtering, vision read/encode, non-vision zero file reads, read failure counting, and aggregate budget truncation; assert the result never exposes bytes or base64 through `image_refs`.
- [ ] Step 2: Add `test_empty_image_context_converts_refs_to_fallback`; pass config containing explicit empty `image_payload`/`current_image_ids`, assert `_image_ctx` returns a non-`None` empty context, and assert `build_context` converts every `image_ref` into `[图片已省略...]` text.
- [ ] Step 3: Add `test_chat_budget_drop_note_is_propagated` and `test_all_unreadable_chat_images_report_omission`; assert the model receives the exact omitted-image count rather than silently reverting to plain text.
- [ ] Step 4: Run the new tests and expect FAIL because chat owns duplicated preparation, `dropped_by_budget` is not passed to state construction, and `_image_ctx` treats explicit empty maps as no context.
- [ ] Step 5: Implement `multimodal_input.py` using `AttachmentRepository.get(user_id, id)` and `AttachmentService.read_file`; calculate effective model vision once, skip disk reads for non-vision models, call `fit_budget`, and set `omitted_count = candidate_count - len(image_refs)` including read failures and budget drops.
- [ ] Step 6: Refactor chat to call the shared preparation function; keep route-level attachment validation and message attachment persistence, remove ownerless `get_attachment_by_id` from image loading, and build graph configurable data through `image_config`.
- [ ] Step 7: Extend multimodal message construction so `candidate_count > 0` always produces a precise non-vision or omission note even when no image payload survives; preserve exactly `HumanMessage(content=text)` when `candidate_count == 0`.
- [ ] Step 8: Change `_image_ctx` to detect key presence rather than truthiness: explicit empty image keys return an empty rendering context, while configurations with no image keys preserve the current no-image fast path.
- [ ] Step 9: Run `tests/test_multimodal.py tests/test_chat_attachments.py tests/test_chat_stream.py`; assert existing chat persistence, SSE, and checkpoint no-base64 tests remain green.
- [ ] Step 10: Commit Task 6 files with message `refactor(multimodal): share owner-aware image preparation`.

---

## Task 7: Feed Task images to vision models and make interrupt/resume media-safe

**Files:**
- Modify: `app/orchestration/task_run.py`
- Modify: `app/orchestration/task_worker.py`
- Modify: `app/orchestration/chat_stream.py:297-445`
- Modify: `tests/test_tasks_api.py`
- Modify: `tests/test_interrupt_stream.py`
- Modify: `tests/test_json_file_saver.py`

**Interfaces:**
- Consumes: normalized `task.input["attachment_ids"]`, task owner ID, shared `prepare_image_input`, and the Task agent's `resolve_effective_model(agent)`.
- Produces: initial Task graph state with lightweight refs and graph configurable with in-memory payload; `Task.id` remains the LangGraph thread ID.
- Produces: resume calls that never re-read attachments and always pass an explicit empty image context, converting persisted refs to fallback text.

- [ ] Step 1: Add e2e-style runner test `test_task_vision_hydrates_image_and_checkpoint_contains_no_base64`; submit a Task with an owned PNG and vision model, capture the model request, assert the standard `{type: "image", source_type: "base64", mime_type: "image/png"}` block decodes to source bytes, and assert Task JSON, events, run logs, and every checkpoint file omit the base64 string.
- [ ] Step 2: Add `test_task_non_vision_does_not_read_attachment`; assert the read function is not called and the model receives a note naming the image count plus the original message.
- [ ] Step 3: Add `test_task_missing_file_after_submit_degrades_and_completes`; remove the file after Task creation, assert runner uses owner-aware lookup, completes instead of failing the whole Task, and sends an omission note without base64.
- [ ] Step 4: Add `test_task_image_budget_keeps_order_and_reports_omitted_count`; create ordered images crossing the configured budget and assert only the retained prefix is hydrated and the omitted count is present in model-visible text.
- [ ] Step 5: Add `test_task_resume_does_not_read_or_replay_images`; make the first vision call interrupt on a confirm-required tool, resume with approval, assert no attachment read occurs on resume, no image block/base64 is replayed, and the historical ref is rendered as `[图片已省略...]`.
- [ ] Step 6: Add `test_plain_task_input_remains_byte_identical`; compare the no-attachment initial HumanMessage and final Task output/event shape against the existing fixture and assert no image configurable keys are added.
- [ ] Step 7: Run these tests and expect FAIL because `task_run` currently calls `build_initial_state` with text only and creates graph config without image context.
- [ ] Step 8: In `run_task_graph`, normalize `attachment_ids`, prepare owner-aware images after loading the Task and agent, pass refs/counts to `build_initial_state`, and pass `PreparedImageInput` into `_run_graph_common`; merge `image_config(prepared)` into `graph_config["configurable"]` without persisting it.
- [ ] Step 9: In `resume_task_graph` and the SSE `resume_stream_events` path, do not call preparation or disk reads; merge `image_config(None, force_context=True)` into graph config so checkpoint refs render as fallback text.
- [ ] Step 10: On interrupt, persist only canonical attachment IDs already present in Task input/pending input; never persist MIME, file paths, bytes, or payload objects.
- [ ] Step 11: Run Task, interrupt, chat attachment, multimodal, and checkpointer suites; search the temporary FileStore/checkpoint output for a known base64 sentinel and expect zero matches.
- [ ] Step 12: Commit Task 7 files with message `feat(tasks): support checkpoint-safe image input`.

---

## Task 8: Close integration, documentation, and review gates

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `progress.md`
- Verify: `docs/plans/2026-08-28-task-api-docker-sandbox-task-multimodal.md`

**Interfaces:**
- Consumes: completed Tasks 1-7 and the existing local single-process architecture.
- Produces: accurate operator instructions for building the sandbox image, explicit Docker failure behavior, the backward-compatible Task attachment contract, and a progress ledger with exact verification results.

- [ ] Step 1: Update README Task examples to show optional `attachment_ids`, state that only images are model inputs in this scope, and document that resume converts historical images to omission text rather than replaying media.
- [ ] Step 2: Replace the Docker sandbox “not implemented” row with the exact `tl_bash`-only scope, fixed network-none policy, image build command, no-auto-pull behavior, resource defaults, and explicit daemon/image error semantics; leave Webhook rows untouched because item 3 is excluded.
- [ ] Step 3: Add the six sandbox settings and comments to `.env.example`; do not add secrets or Docker socket settings.
- [ ] Step 4: Run backend targeted suites for tasks, cancellation, placeholder, Docker sandbox, executor, file ops, interrupts, multimodal, attachments, chat, and checkpoint recovery.
- [ ] Step 5: Run the complete backend gates: `pytest tests/`, `ruff check .`, and the project Test/Review/Simplify workflow; record exact pass/skip/warning counts in `progress.md`.
- [ ] Step 6: Run a real local smoke only when Docker Desktop and `libao-sandbox:py312-v1` are available; verify `tl_bash` can read/write the temporary workspace, cannot reach the network, cannot see host files outside the mount, and leaves no labeled container after success, timeout, or cancellation. Record “not run: Docker unavailable” rather than weakening policy when unavailable.
- [ ] Step 7: Self-review the plan-to-implementation map: item 1 maps to Task 1; item 2 maps to Tasks 2-4; item 4 maps to Tasks 5-7; item 3 has no changed source file; every new public or runtime interface has a named failing test.
- [ ] Step 8: Create a final Conventional Commit `feat(agent): close task sandbox and multimodal gaps` only if the user wants one squashed commit; otherwise retain the three feature commits and one fix commit listed above. Do not commit unrelated user changes.

---

## Explicit Non-Goals

- Webhook/hook endpoints, persistence, authentication, idempotency, UI, and documentation changes.
- `microvm` execution.
- Docker isolation for MCP tools, HTTP tools, file read/write helpers, or arbitrary Python handlers.
- Network-enabled containers or domain-level allowlists.
- Automatic image pulls or host-shell fallback.
- PDF/Office extraction, OCR, or document injection into Tasks.
- Replaying image bytes after interrupt/resume or across later turns.
- Multi-instance workers, Redis queues, or distributed container scheduling.
