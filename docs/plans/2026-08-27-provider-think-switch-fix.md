# Provider Think Switching Fix Implementation Plan

**Goal:** Make the existing Provider enable switch select the configured DeepSeek/GLM model immediately and uniquely so DeepSeek reasoning reaches the existing `thinking` stream again.
**Architecture:** Keep the frontend contract unchanged: `PATCH /settings/providers/{id}` with `enabled=true` becomes the canonical activation path by delegating to `ProviderService.activate`. Non-activation field patches keep their current partial-update behavior. Regression coverage proves that activating DeepSeek after GLM disables GLM and synchronizes the in-process model, base URL, and API key used by `stream_core`/`LLMService`.
**Global Constraints:** Preserve all unrelated uncommitted multimodal changes in the worktree.
**Global Constraints:** Do not modify persisted user configuration under `~/.LiBao`.
**Global Constraints:** Keep `api_key` write-only in API serialization.
**Global Constraints:** Keep the existing `ReasoningChatOpenAI` parsing and SSE `thinking` pipeline unchanged.

---

## Task 1: Route PATCH activation through the unique hot-sync path

**Files:**
- Modify: `app/services/provider.py:62-86`
- Test: `tests/test_provider.py`

**Interfaces:**
- Consumes: `ProviderService.patch(db, user, provider_id, **fields) -> ProviderConfig`, `ProviderService.activate(db, user, provider_id) -> ProviderConfig`, and the frontend payload `{"enabled": true}`.
- Produces: `PATCH enabled=true` semantics equivalent to `activate`: exactly one non-deleted Provider has `enabled=True`, and `get_settings().llm_model`, `llm_base_url`, and `llm_api_key` match that Provider before the request returns.

- [x] Step 1: Add a failing async regression test `test_provider_patch_enable_activates_uniquely_and_hot_syncs` to `tests/test_provider.py` with two providers (`glm-5.3-flash` initially enabled and `deepseek-v4-flash` disabled), monkeypatch runtime Settings to the GLM values, call `svc.patch(session, user, deepseek.id, enabled=True)`, then assert GLM is disabled, DeepSeek is enabled, and runtime model/base/key equal `deepseek-v4-flash`, `https://api.deepseek.com/v1`, and `deepseek-key`.
- [x] Step 2: Run `.\.venv\Scripts\pytest.exe -p no:cacheprovider tests/test_provider.py::test_provider_patch_enable_activates_uniquely_and_hot_syncs -q`; expect FAIL because `patch()` currently only sets the target flag and never synchronizes Settings.
- [x] Step 3: In `ProviderService.patch`, after ownership validation and before generic field mutation, detect `fields.get("enabled") is True` and delegate to `self.activate(db, user, provider_id)`. Do not duplicate activation logic and do not alter the semantics of `enabled=False` or unrelated partial fields.
- [x] Step 4: Run `.\.venv\Scripts\pytest.exe -p no:cacheprovider tests/test_provider.py::test_provider_patch_enable_activates_uniquely_and_hot_syncs -q`; expect PASS.
- [x] Step 5: Run `.\.venv\Scripts\pytest.exe -p no:cacheprovider tests/test_provider.py tests/test_llm.py tests/test_chat_stream.py -q`; expect all existing Provider, DeepSeek reasoning extraction, and SSE thinking persistence tests to pass.

---

## Task 2: Verify the effective-model regression boundary

**Files:**
- Test: `tests/test_provider.py`
- Verify: `app/orchestration/stream_core.py:121-126`
- Verify: `app/core/llm.py:33-101`

**Interfaces:**
- Consumes: the runtime Settings synchronized by Task 1 and `resolve_effective_model(agent) -> str` when `agent.model == ""`.
- Produces: evidence that the configured `deepseek-v4-flash` is the model selected after GLM-to-DeepSeek activation, allowing the existing `ReasoningChatOpenAI` adapter to emit `additional_kwargs["reasoning_content"]`.

- [x] Step 1: Extend `test_provider_patch_enable_activates_uniquely_and_hot_syncs` with an agent-like `SimpleNamespace(model="")` and assert `resolve_effective_model(agent) == "deepseek-v4-flash"` after the PATCH activation.
- [x] Step 2: Run `.\.venv\Scripts\pytest.exe -p no:cacheprovider tests/test_provider.py::test_provider_patch_enable_activates_uniquely_and_hot_syncs tests/test_llm.py::test_reasoning_chunk_conversion_extracts_reasoning -q`; expect PASS and thereby cover both the selected model and its DeepSeek reasoning adapter.
- [x] Step 3: Run `.\.venv\Scripts\ruff.exe check app/services/provider.py tests/test_provider.py`; expect no lint errors.
- [x] Step 4: Record completed commands and results in `progress.md` without changing existing historical entries.
