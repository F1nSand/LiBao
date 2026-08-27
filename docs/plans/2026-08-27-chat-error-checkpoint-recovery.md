# Chat Error Checkpoint Recovery Implementation Plan

**Goal:** Ensure one transient Agent error cannot permanently poison a conversation, while automatically recovering conversations already affected by legacy unserializable error checkpoints.
**Architecture:** Normalize LangGraph `__error__` pending writes at the `JsonFileSaver` persistence boundary into stable plain data instead of serializing exception objects. Add a read-side compatibility fallback for legacy `type=not_implemented` error writes so existing checkpoints can load; LangGraph's normal fresh-input path will then discard the unfinished failed task and continue from the same thread state.
**Global Constraints:** Preserve failed user messages in the append-only transcript, but do not replay the failed graph task as successful model context.
**Global Constraints:** Do not modify or delete real data under `~/.LiBao`.
**Global Constraints:** Preserve all unrelated uncommitted multimodal changes in the worktree.
**Global Constraints:** Commit only task-owned implementation, tests, and plan artifacts; do not stage unrelated user changes.

---

## Task 1: Make pending error writes stable and backward compatible

**Files:**
- Modify: `app/orchestration/checkpointer.py:118-167`
- Test: `tests/test_json_file_saver.py`

**Interfaces:**
- Consumes: `JsonFileSaver.put_writes(config, writes, task_id, task_path="")` where LangGraph writes `("__error__", Exception)` and legacy persisted values whose LangChain JSON has `type="not_implemented"`.
- Produces: `JsonFileSaver.get_tuple(config) -> CheckpointTuple | None` that never fails solely because a pending `__error__` value is an unsupported exception type; non-error channels retain current strict deserialization.

- [ ] Step 1: Add failing test `test_error_pending_write_roundtrip_is_loadable` to `tests/test_json_file_saver.py`: create checkpoint `c1`, call `put_writes` with `[("__error__", RuntimeError("boom"))]`, then assert `aget_tuple` returns one `__error__` pending write without raising.
- [ ] Step 2: Add failing test `test_legacy_not_implemented_error_write_is_loadable` that writes a legacy `lc_dumps(RuntimeError("boom"))` value directly into checkpoint `c1`'s `writes`, then asserts `aget_tuple` returns the checkpoint and an `__error__` pending write without raising `NotImplementedError`.
- [ ] Step 3: Run `.\.venv\Scripts\pytest.exe -p no:cacheprovider tests/test_json_file_saver.py::test_error_pending_write_roundtrip_is_loadable tests/test_json_file_saver.py::test_legacy_not_implemented_error_write_is_loadable -q`; expect both tests to FAIL at `lc_loads(val)` before implementation.
- [ ] Step 4: In `app/orchestration/checkpointer.py`, add private helpers that serialize `__error__` exception values as a plain dict containing only `error_type`, and deserialize pending writes with a `NotImplementedError` fallback only for the `__error__` channel; preserve `lc_dumps`/`lc_loads` behavior for every other channel.
- [ ] Step 5: Run the two targeted tests again; expect PASS.

---

## Task 2: Prove the same conversation recovers after one model error

**Files:**
- Modify: `tests/test_chat_stream.py`
- Verify: `app/orchestration/stream_core.py:248-302`
- Verify: `app/orchestration/chat_stream.py:173-285`

**Interfaces:**
- Consumes: `chat_stream_events(..., graph=build_graph(JsonFileSaver(...)), conversation=<same id>, model_override=<fail once model>)` called twice with the same conversation/thread.
- Produces: first call ends with SSE `error`; second fresh user message on the same conversation ends with SSE `done`, while the first failed user message remains in `MessageRepository` and no failed assistant message is fabricated.

- [ ] Step 1: Add failing async test `test_chat_recovers_same_thread_after_model_error` to `tests/test_chat_stream.py` using a stateful model whose first `ainvoke` raises `RuntimeError("temporary model failure")` and whose second returns `AIMessage(content="恢复成功")`; compile the graph with a temporary `JsonFileSaver`.
- [ ] Step 2: In the test, collect the first call's event types and assert its last event is `error`; invoke `chat_stream_events` again with the same conversation and graph, assert the second call ends in `done` and contains no `error`; assert persisted roles are `["user", "user", "assistant"]`.
- [ ] Step 3: Run `.\.venv\Scripts\pytest.exe -p no:cacheprovider tests/test_chat_stream.py::test_chat_recovers_same_thread_after_model_error -q`; expect PASS after Task 1 and thereby verify the complete persistence→restore→fresh-input flow.
- [ ] Step 4: Run `.\.venv\Scripts\pytest.exe -p no:cacheprovider tests/test_json_file_saver.py tests/test_chat_stream.py tests/test_graph.py -q`; expect all checkpoint, SSE error, and chat persistence tests to pass.
- [ ] Step 5: Run `.\.venv\Scripts\ruff.exe check app/orchestration/checkpointer.py tests/test_json_file_saver.py tests/test_chat_stream.py`; expect no lint errors.

---

## Task 3: Close quality gates and create an archival commit

**Files:**
- Update: `progress.md`
- Include: `docs/plans/2026-08-27-provider-think-switch-fix.md`
- Include: `docs/plans/2026-08-27-chat-error-checkpoint-recovery.md`
- Include owned hunks only: `app/services/provider.py`, `tests/test_provider.py`, `app/orchestration/checkpointer.py`, `tests/test_json_file_saver.py`, `tests/test_chat_stream.py`

**Interfaces:**
- Consumes: passing Test/Review/Simplify gates and the dirty worktree ownership boundary recorded above.
- Produces: one Conventional Commit that archives both requested bug fixes without staging unrelated multimodal/provider-capability work.

- [ ] Step 1: Run the project full test suite and record any failures, distinguishing task regressions from concurrent unrelated worktree failures with exact test names.
- [ ] Step 2: Run Review and Simplify gates on task-owned hunks; fix only user-approved correctness findings and rerun affected tests.
- [ ] Step 3: Build a selective index containing only task-owned hunks; inspect `git diff --cached --check` and `git diff --cached --stat` before committing.
- [ ] Step 4: Commit with Conventional Commit message `fix(agent): recover conversations after model errors`.
- [ ] Step 5: Show the commit id and verify `git status --short` still contains all unrelated pre-existing changes unstaged.

