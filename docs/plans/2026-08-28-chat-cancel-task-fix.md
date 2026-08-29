# Chat Cancellation Task Lifecycle Plan

**Goal:** Make every `/chat/stream` run a cancellable Task whose producer, finalization, and cancellation share one lifecycle so cancellation never resurrects a run or persists a partial assistant result.

**Architecture:** The existing in-process task registry remains the execution-control plane. A per-task asyncio guard serializes cancellation against finalization, while a durable Task status remains the source of truth. Chat streams keep the same SSE contract and expose `task_id` in `message_start`; interrupt/resume keeps the same Task and checkpoint thread.

**Global Constraints:**

- Do not add Provider fields or model capability configuration.
- Keep the existing `/chat/stream`, `/tasks/{id}/cancel`, and `/tasks/{id}/resume` JSON/SSE contracts backward compatible.
- Cancellation must leave Task status `cancelled`, suppress `on_final`, and avoid assistant-message/run-log persistence for the cancelled run.
- Preserve disconnect semantics: an ordinary client disconnect still drains the graph and finalizes normally; an explicit Task cancellation must not drain.
- Normal chat and its first interrupt/resume use the same Task id; the pre-existing SSE second-interrupt successor-Task behavior is outside this cancellation fix. JSON task resume continues to preserve the original checkpoint thread.
- Do not alter user data outside test-created conversations/tasks and temporary workspaces.

---

## Task 1: Task-level cancellation/finalization coordination

**Files:**

- Modify: `app/orchestration/task_worker.py`
- Modify: `app/services/task.py`
- Modify: `app/storage/models/task.py`
- Test: `tests/test_cancel_inflight.py`, `tests/test_tasks_api.py`

**Interfaces:**

- Consumes: `task_id: str`, the existing `_RUNNING` producer registry, and `Task.status`.
- Produces: `task_guard(task_id: str) -> asyncio.Lock` (or an equivalent async context manager), cancellation intent that survives producer registration, and an idempotent `TaskService.cancel()` that serializes with finalization.

- [x] Step 1: Add failing tests for cancellation intent arriving before producer registration, for cancellation competing with finalization, and for the Task model documentation matching chat Tasks.
- [x] Step 2: Run `uv run pytest tests/test_cancel_inflight.py tests/test_tasks_api.py -q` and verify the new race tests fail against the current implementation.
- [x] Step 3: Implement a per-task guard in `task_worker.py`; make `register_running_task()` cancel a producer when a prior cancel intent exists instead of discarding that intent; make cleanup remove the guard and intent only after the matching producer exits.
- [x] Step 4: Make `TaskService.cancel()` acquire the same guard used by chat finalization, re-read the Task, reject `done`/`cancelled` with `40902`, then persist `cancelled` and publish the terminal event.
- [x] Step 5: Update the Task model docstring to state that chat runs also create Tasks.
- [x] Step 6: Run the focused tests and verify PASS.

---

## Task 2: Chat stream lifecycle and race-safe finalization

**Files:**

- Modify: `app/api/routers/chat.py`
- Modify: `app/orchestration/chat_stream.py`
- Modify: `app/orchestration/stream_core.py`
- Test: `tests/test_cancel_inflight.py`, `tests/test_chat_stream.py`

**Interfaces:**

- Consumes: `Task` passed into `chat_stream_events()`, `run_id` passed into `stream_graph_events()`, and `task_guard()` from Task 1.
- Produces: `message_start.payload.task_id`, no graph start after a pre-start cancellation, and a finalization section that checks status and persists the final assistant result while holding the task guard.

- [x] Step 1: Add failing tests for a pre-`message_start` cancellation, a slow tool cancellation, a cancel/final race, and a normal chat run that reaches `done` with exactly one final assistant message.
- [x] Step 2: Run the focused tests and verify each new behavior fails or exposes the current race.
- [x] Step 3: Before expensive preparation and before yielding `message_start`, re-read a supplied Task and return without starting the graph when it is already `cancelled`.
- [x] Step 4: Keep `run_id=task.id` registration for chat and resume streams; ensure a pending cancellation is honored when registration happens after the HTTP cancel request.
- [x] Step 5: Wrap chat `on_final()` status check, assistant-message/run-log persistence, and Task `done` transition in the per-task guard; if the Task is cancelled, return an empty payload without persistence.
- [x] Step 6: Preserve ordinary disconnect draining and ensure explicit cancellation skips `on_final` and emits no `done` frame.
- [x] Step 7: Run the focused tests and verify PASS.

---

## Task 3: Regression and handoff verification

**Files:**

- Modify: `tests/test_cancel_inflight.py`
- Modify: `tests/test_chat_stream.py`
- Modify: `progress.md`
- Modify: `progress-attachment-context.md`

**Interfaces:**

- Consumes: the completed Task 1–2 lifecycle.
- Produces: executable regression coverage for running cancellation, tool cancellation, cancel/done race, cancellation followed by a new run, and normal completion.

- [x] Step 1: Run `uv run pytest tests/test_cancel_inflight.py tests/test_chat_stream.py tests/test_tasks_api.py -q`。
- [x] Step 2: Run `uv run pytest -q` and `uv run ruff check .`。
- [x] Step 3: Run the frontend typecheck, lint, unit tests, and the real backend E2E smoke if the local servers are available。
- [x] Step 4: Mark the cancellation handoff item done with exact test counts and record any environment-only skips。
