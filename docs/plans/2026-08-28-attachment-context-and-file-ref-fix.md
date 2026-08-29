# Dynamic Multimodal and File Context Implementation Plan

**Goal:** 让未知 OpenAI-compatible 模型在收到图片时不再被本地模型名单提前拦截，并让当前支持上传的文本、PDF、DOCX 与工作区文件引用真正进入 Agent 当前轮上下文。

**Architecture:** 图片能力采用 `supported / unsupported / unknown` 三态：优先读取已识别网关的同源能力元数据，其次只采信 LiteLLM 目录的正向结论，仍未知时直接执行用户本来请求的那次携图调用；成功或明确的模态拒绝只写进程内短期缓存。普通文件由确定性解析器抽取、分块和限额，选中的文本与图片载荷都只经 LangGraph `configurable` 在模型调用边界水合，不写入 Message 或 checkpoint；消息日志只保存附件展示元数据和轻量 `file_refs`。

**Global Constraints:** 不新增、不修改 Provider 的 API、存储字段或前端配置控件；现存 `capabilities` / `llm_vision_declared` 为兼容保留，但不再拥有图片请求的否决权。

**Global Constraints:** `unknown` 绝不能等同于 `unsupported`；模型名 pattern 和第三方目录只能提供 `supported` 正向提示，不能仅因缺条目而拒绝图片。

**Global Constraints:** 未知模型的首次真实携图请求就是能力验证，不额外发送探针请求；失败后不得静默删图并自动改成纯文本重试。

**Global Constraints:** 只有明确的 HTTP 400/415/422 模态拒绝才缓存 `unsupported`；鉴权、限流、网络、超时、服务端错误、上下文超限和含糊的 400 均保持 `unknown`。

**Global Constraints:** 图片 base64、文件抽取全文和本轮选中的文件上下文不得写入 Message、Task、run log、事件或 checkpoint；历史图片继续降级为 `[图片已省略…]`。

**Global Constraints:** 文件内容始终按不可信用户输入处理，只能附加到当前 HumanMessage 的模型侧副本，不能进入静态 system prompt、`project_overlay` 或长期记忆。

**Global Constraints:** 每条消息最多 10 个上传附件和 10 个 `file_refs`；文档分块固定为 1,200 字符、120 字符重叠，每个来源最多注入 12,000 字符，单轮全部文件来源最多注入 48,000 字符。

**Global Constraints:** 当前文件范围为 UTF-8/可解码文本与代码、TXT、Markdown、文本型 PDF、DOCX；旧二进制 `.doc` 从上传白名单移除并返回 40012，扫描 PDF 无正文时明确提示“可能为扫描件，未执行 OCR”。

**Global Constraints:** 图片上传分析保持 `uploaded -> analyzing -> ready | failed` 兼容，但 `ready` 只表示上传准备完成，不代表模型已分析；上传阶段不调用 VLM，不产生第二笔模型费用。

**Global Constraints:** 保留并兼容当前未提交的多模态、Provider 热同步、Task 恢复和 Docker 修复；执行时不得覆盖前端 Agent 或用户的其它未提交改动。

---

## Task 1: Introduce tri-state runtime vision capability resolution

**Files:**
- Create: `app/core/model_capabilities.py`
- Modify: `app/core/vision.py`
- Test: `tests/test_model_capabilities.py`

**Interfaces:**
- Produces: `VisionCapability(StrEnum)` with exact values `SUPPORTED = "supported"`, `UNSUPPORTED = "unsupported"`, and `UNKNOWN = "unknown"`.
- Produces: immutable `ModelCapabilityKey(base_url: str, model: str, transport: str = "openai-chat-completions")`; `base_url` is normalized with `resolve_openai_base_url`, stripped of credentials and trailing slash, and the API key is never part of the key.
- Produces: immutable `VisionDecision(state: VisionCapability, source: str, key: ModelCapabilityKey)`.
- Produces: `ModelCapabilityResolver.resolve_vision(key: ModelCapabilityKey, api_key: str | None = None) -> VisionDecision`, `record_success(key) -> None`, `record_unsupported(key) -> None`, and `clear() -> None`.
- Produces: `get_model_capability_resolver() -> ModelCapabilityResolver`, the process-local singleton used by preparation and model execution.
- Produces: `is_explicit_vision_rejection(exc: Exception) -> bool`; it returns true only for status 400/415/422 plus either structured codes `unsupported_media_type`, `unsupported_content_type`, `image_not_supported`, `vision_not_supported`, `invalid_image_url`, or a message containing an image token (`image`, `image_url`, `vision`, `multimodal`, `图片`, `视觉`) and a rejection token (`unsupported`, `not support`, `does not support`, `不支持`, `无法处理`).
- Consumes: `httpx.AsyncClient` and installed `litellm.get_model_info`; network discovery timeout is 1.5 seconds.

- [ ] Step 1: Add `test_unknown_model_is_not_unsupported`, `test_litellm_positive_hint_marks_supported`, and `test_litellm_false_or_missing_stays_unknown`; assert no model-name miss can produce `UNSUPPORTED`.
- [ ] Step 2: Add adapter tests with `httpx.MockTransport`: OpenRouter exact model metadata containing `architecture.input_modalities=["text","image"]` returns supported and an explicit list without `image` returns unsupported; Ollama `/api/show` reads `capabilities`; LM Studio `/api/v0/models` reads `type="vlm"`; HTTP/auth/timeout/model-not-found responses remain unknown.
- [ ] Step 3: Add `test_capability_cache_is_scoped_by_base_model_and_transport` and a fake clock; assert positive entries live 86,400 seconds, negative entries live 3,600 seconds, discovery-unknown entries suppress repeat metadata calls for 300 seconds, and a different base URL or model never reuses the entry.
- [ ] Step 4: Add table-driven rejection-classifier tests proving the exact structured codes and bilingual message conjunction above are accepted, while 401, 429, 500, timeout, context-length errors, and ambiguous 400 responses are rejected by the classifier.
- [ ] Step 5: Run `uv run pytest tests/test_model_capabilities.py -q`; expect collection/import failures because the module and interfaces do not exist.
- [ ] Step 6: Implement the enum, immutable key/decision types, TTL cache, rejection classifier, and three metadata adapters. OpenRouter discovery is enabled only for host `openrouter.ai`; Ollama only for port `11434`; LM Studio only for port `1234`; every adapter calls the same origin as the configured model endpoint and never logs or persists the API key.
- [ ] Step 7: In the fallback chain, accept only `litellm.get_model_info(model).get("supports_vision") is True`; false, null, missing model, exceptions, and model-name pattern misses must return `UNKNOWN`.
- [ ] Step 8: Reduce `app/core/vision.py` to compatibility helpers that can return a positive hint but cannot return an authoritative negative decision; mark `supports_vision(model, declared)` unused by the chat/Task attachment paths without deleting it in this task.
- [ ] Step 9: Run `uv run pytest tests/test_model_capabilities.py -q`; expect PASS.
- [ ] Step 10: Run `uv run ruff check app/core/model_capabilities.py app/core/vision.py tests/test_model_capabilities.py`; expect no errors.
- [ ] Step 11: Commit only Task 1 files with message `feat(multimodal): add runtime vision capability resolver`.

---

## Task 2: Send images for unknown models and learn at the model-call boundary

**Files:**
- Modify: `app/core/errors.py`
- Modify: `app/core/multimodal.py`
- Modify: `app/orchestration/multimodal_input.py`
- Modify: `app/orchestration/stream_core.py`
- Modify: `app/orchestration/chat_stream.py`
- Modify: `app/orchestration/task_run.py`
- Modify: `app/orchestration/context_builder.py`
- Modify: `app/orchestration/nodes/agent_execute.py`
- Test: `tests/test_multimodal.py`
- Test: `tests/test_chat_attachments.py`
- Test: `tests/test_tasks_api.py`

**Interfaces:**
- Consumes: `VisionCapability`, `VisionDecision`, `ModelCapabilityKey`, `get_model_capability_resolver()`, and `is_explicit_vision_rejection()` from Task 1.
- Produces: `ERR_MULTIMODAL_UNSUPPORTED = 60005` for a model endpoint that explicitly rejects image input.
- Produces: `PreparedImageInput(..., capability: VisionCapability, capability_key: ModelCapabilityKey)`; the old `vision: bool` field is removed.
- Produces: `prepare_image_input(..., effective_model: str, effective_base_url: str | None = None) -> PreparedImageInput`; `SUPPORTED` and `UNKNOWN` both read, budget, encode, and create refs, while only `UNSUPPORTED` performs zero file reads.
- Produces: graph configurable keys `image_capability_state` and `image_capability_key` beside the existing ephemeral `image_payload` and `current_image_ids`.
- Produces: `build_initial_state(..., image_capability: VisionCapability = VisionCapability.UNKNOWN)`; it never calls `supports_vision` again and treats only `UNSUPPORTED` as the no-image branch.

- [ ] Step 1: Replace the old unknown/default-deny assertions with `test_glm_53_flash_unknown_capability_reads_and_prepares_image`; use model `glm-5.3-flash`, an unrecognized base URL, and no catalog metadata, then assert the image file is read and refs/payload are produced with capability `UNKNOWN`.
- [ ] Step 2: Add `test_authoritative_unsupported_never_reads_image` by seeding the resolver cache with `UNSUPPORTED`; assert candidate count is preserved, file reads stay at zero, and the model-visible note states that the endpoint does not accept image input without claiming a static model-list verdict.
- [ ] Step 3: Add `test_unknown_image_success_records_supported`: run the graph with a capturing model, assert the first request contains the standard base64 image block, then assert the exact capability key is cached as supported.
- [ ] Step 4: Add `test_explicit_image_rejection_is_not_retried_and_records_negative`: a fake model raises a 400 exception with structured code `vision_not_supported`; assert `ainvoke` is called exactly once, SSE emits code 60005 with a clear message, and the capability key is cached unsupported.
- [ ] Step 5: Add parameterized `test_transient_image_failure_does_not_poison_capability_cache` for 401, 429, 500, timeout, and context-length failures; assert each remains unknown and surfaces through the existing LLM failure path.
- [ ] Step 6: Update Task image tests so an unknown Task model sends its first image, Task interrupt/resume still never rereads or replays image bytes, and success/error capability recording is shared with chat.
- [ ] Step 7: Run `uv run pytest tests/test_multimodal.py tests/test_chat_attachments.py tests/test_tasks_api.py -q`; expect failures in current default-deny behavior and missing capability propagation.
- [ ] Step 8: Refactor image preparation to resolve capability before disk access; remove every chat/Task call to `get_settings().llm_vision_declared` or `supports_vision` as an admission gate.
- [ ] Step 9: Pass the decision and key through `image_config`; render image refs whenever state is supported or unknown, while forced empty contexts on plain turns/resume continue converting historical refs to omission text.
- [ ] Step 10: Wrap only the image-bearing `model.ainvoke` in `agent_execute_node`: on success record supported; on an explicit rejection record unsupported and raise `AppError(ERR_MULTIMODAL_UNSUPPORTED, "当前模型接口明确拒绝图片输入；图片未被分析，请更换模型或检查该接口的多模态请求格式。")`; do not retry without images.
- [ ] Step 11: Update `stream_core` graph-error handling to preserve `AppError.code`, `message`, and `retryable`; all non-`AppError` exceptions continue to emit 60001.
- [ ] Step 12: Run the Task 2 pytest command again; expect PASS and assert checkpoint/run-log/Event files contain neither source image bytes nor base64.
- [ ] Step 13: Run `uv run ruff check app/core/errors.py app/core/multimodal.py app/orchestration/multimodal_input.py app/orchestration/stream_core.py app/orchestration/chat_stream.py app/orchestration/task_run.py app/orchestration/context_builder.py app/orchestration/nodes/agent_execute.py tests/test_multimodal.py tests/test_chat_attachments.py tests/test_tasks_api.py`; expect no errors.
- [ ] Step 14: Commit only Task 2 files with message `fix(multimodal): optimistically deliver images to unknown models`.

---

## Task 3: Replace placeholder attachment analysis with deterministic document extraction

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `app/services/document_extraction.py`
- Modify: `app/storage/attachment_analysis.py`
- Modify: `app/services/attachment.py`
- Modify: `tests/test_attachments_api.py`
- Test: `tests/test_document_extraction.py`

**Interfaces:**
- Produces: immutable `ExtractedDocument(text: str, kind: str, truncated: bool, warning: str | None)`.
- Produces: `extract_document(data: bytes, *, content_type: str, filename: str) -> ExtractedDocument`; TXT/Markdown and ordinary text/code use UTF-8 with replacement, PDF uses `pypdf.PdfReader`, and DOCX uses `python-docx` XML block iteration so paragraphs and tables retain document order.
- Produces: `chunk_text(text: str, *, size: int = 1200, overlap: int = 120) -> tuple[str, ...]` with deterministic Unicode character boundaries.
- Produces: image analysis result `{"type": "image", "text": None, "reason": "analysis_on_send"}`.
- Preserves: `/attachments/{id}/analysis` response fields and attachment status transitions.

- [ ] Step 1: Add extractor tests using generated in-memory TXT/Markdown, a minimal PDF fixture, and a DOCX fixture with paragraph/table/paragraph order; assert unique nonce text is returned in source order and corrupt PDF/DOCX produces a controlled extraction error.
- [ ] Step 2: Add `test_chunk_text_uses_1200_chars_and_120_overlap` and assert reconstruction boundaries, empty input, exact-size input, and deterministic repeated calls.
- [ ] Step 3: Change `test_analyze_image_degrades` to `test_image_upload_analysis_is_neutral`: assert status is ready, reason is `analysis_on_send`, text/summary is null, and neither `no_vision_model` nor “无法分析” appears.
- [ ] Step 4: Add upload validation proving `application/msword` / `.doc` returns 40012, while TXT, Markdown, PDF, and DOCX remain accepted.
- [ ] Step 5: Run `uv run pytest tests/test_document_extraction.py tests/test_attachments_api.py -q`; expect missing dependency/module failures and the old image placeholder assertion to fail.
- [ ] Step 6: Run `uv add pypdf python-docx`; verify both `pyproject.toml` and `uv.lock` change and no unrelated dependency is removed.
- [ ] Step 7: Implement the pure extractor and chunker; PDF pages are joined with page markers, DOCX tables use tab-separated cells and newline-separated rows, NUL-bearing unknown binaries are rejected, and all parser exceptions are converted to one controlled `DocumentExtractionError` without including file bytes.
- [ ] Step 8: Update the upload whitelist and background analysis: images become neutral `analysis_on_send`; extractable documents cache at most the first 50,000 characters plus `truncated`; scanned/no-text PDFs finish ready with null text and warning “未提取到文本，文件可能为扫描件；当前未执行 OCR”.
- [ ] Step 9: Run the Task 3 pytest command again; expect PASS.
- [ ] Step 10: Run `uv run ruff check app/services/document_extraction.py app/storage/attachment_analysis.py app/services/attachment.py tests/test_document_extraction.py tests/test_attachments_api.py`; expect no errors.
- [ ] Step 11: Commit only Task 3 files with message `feat(attachments): add bounded document extraction`.

---

## Task 4: Inject uploaded document content into the current model turn

**Files:**
- Create: `app/orchestration/document_input.py`
- Modify: `app/orchestration/chat_stream.py`
- Modify: `app/orchestration/task_run.py`
- Modify: `app/orchestration/context_builder.py`
- Modify: `app/orchestration/nodes/agent_execute.py`
- Modify: `app/services/serializers.py`
- Test: `tests/test_document_input.py`
- Test: `tests/test_chat_attachments.py`
- Test: `tests/test_tasks_api.py`

**Interfaces:**
- Consumes: `extract_document()` and `chunk_text()` from Task 3.
- Produces: immutable `PreparedDocumentInput(context_text: str, attachment_refs: tuple[dict[str, Any], ...], omitted: tuple[str, ...])`.
- Produces: `prepare_document_input(db: Any, *, user_id: UUID, attachment_ids: list[str], query: str) -> PreparedDocumentInput`; it performs owner-aware lookup, ignores image MIME for text extraction, and preserves request order.
- Produces: `document_config(prepared: PreparedDocumentInput | None, *, force_context: bool = False) -> dict[str, Any]` with ephemeral key `document_context`.
- Produces: attachment display refs with exact fields `attachment_id`, `mime_type`, `name`, `size`, and `status`; these refs are safe to persist and return to the frontend.

- [ ] Step 1: Add unit tests proving TXT/Markdown/PDF/DOCX extraction, request-order preservation, owner isolation, partial-file failure, empty/scanned PDF warning, per-source 12,000-character cap, and aggregate 48,000-character cap.
- [ ] Step 2: Add BM25 selection tests: split at 1,200/120, rank chunks with the existing `rank-bm25` dependency against tokenized user text, restore selected chunks to source order, and fall back to leading chunks when the user text is empty or tokenization yields no terms.
- [ ] Step 3: Add chat integration `test_text_pdf_docx_attachments_are_visible_only_in_current_model_request`; capture a unique nonce in every format, assert source-labelled blocks `[附件: <name> | <id>]` are present in the latest HumanMessage model copy, and assert persisted Message/checkpoint files contain neither nonce nor extracted context.
- [ ] Step 4: Add `test_document_context_survives_tool_rounds_but_not_next_chat_turn`; within one graph run the context appears on every model call, while the next plain chat turn has no document text and retains only persisted attachment refs.
- [ ] Step 5: Add Task integration proving non-image Task attachments use the same preparation and ephemeral injection, while interrupt/resume does not reread or replay document content.
- [ ] Step 6: Run `uv run pytest tests/test_document_input.py tests/test_chat_attachments.py tests/test_tasks_api.py -q`; expect failures because document attachments are currently ignored by orchestration.
- [ ] Step 7: Implement preparation with a total-source budget ledger. Prefix each selected source with `[附件: {filename} | {attachment_id}]`; append controlled omission notes for unreadable, corrupt, unsupported, or no-text sources without failing other attachments.
- [ ] Step 8: Persist full display refs instead of `{"attachment_id": id}` in chat user messages; keep Task input as UUID lists and keep all extracted text out of persisted structures.
- [ ] Step 9: Extend graph configurable and `_image_ctx` into one model-run attachment context containing image payload plus `document_context`; in `build_context`, modify only a copy of the latest current-turn HumanMessage and append the source-labelled document text after the user text/image blocks.
- [ ] Step 10: Ensure forced empty context on resume/plain turns clears both image and document payloads; no historical document body is rehydrated automatically.
- [ ] Step 11: Run the Task 4 pytest command again; expect PASS.
- [ ] Step 12: Run `uv run ruff check app/orchestration/document_input.py app/orchestration/chat_stream.py app/orchestration/task_run.py app/orchestration/context_builder.py app/orchestration/nodes/agent_execute.py app/services/serializers.py tests/test_document_input.py tests/test_chat_attachments.py tests/test_tasks_api.py`; expect no errors.
- [ ] Step 13: Commit only Task 4 files with message `feat(attachments): inject document context into agent turns`.

---

## Task 5: Complete workspace `file_refs` and replay contracts

**Files:**
- Modify: `app/api/schemas/chat.py`
- Modify: `app/api/routers/chat.py`
- Modify: `app/storage/models/message.py`
- Modify: `app/storage/repositories/message.py`
- Modify: `app/services/serializers.py`
- Modify: `app/orchestration/chat_stream.py`
- Modify: `app/orchestration/document_input.py`
- Test: `tests/test_chat_attachments.py`
- Test: `tests/test_workspace_agent.py`
- Test: `tests/test_conversation_workspace.py`
- Test: `tests/test_workspace_service.py`

**Interfaces:**
- Produces: strict `FileRef(path: str)` with 1..1024 characters and `extra="forbid"`.
- Produces: `ChatMessageInput.attachments` and `file_refs` with `default_factory=list` and `max_length=10`.
- Produces: `Message.file_refs: list = field(default_factory=list)` and `serialize_message(...)["file_refs"]`.
- Produces: `prepare_workspace_file_input(*, workspace_root: str, file_refs: list[FileRef], query: str) -> PreparedDocumentInput`; every path uses `resolve_workspace_path`, must resolve to a regular file, and is labelled `[工作区引用: {relative_path}]`.

- [ ] Step 1: Preserve and complete the already-present uncommitted schema work; add tests for empty path, path longer than 1,024, extra fields, more than 10 attachments, and more than 10 file refs.
- [ ] Step 2: Add route tests proving `file_refs` are accepted only when the resolved conversation has a real `workspace_id`; ordinary conversations with an implicit session workspace return `AppError(40302, "file_refs 仅用于工作区会话")` instead of silently dropping the field.
- [ ] Step 3: Add security tests for absolute paths, `..` escape, symlink escape, missing files, directories, and paths from another workspace; all must return 40302 without exposing the resolved host path.
- [ ] Step 4: Add content tests for UTF-8 code/text, a text-bearing PDF, DOCX, a file larger than 1 MiB, and a NUL-bearing binary. Read at most 1 MiB per workspace source before extraction; label truncation and unsupported binary notes and continue with remaining refs.
- [ ] Step 5: Add replay tests asserting user Message persistence and `GET /conversations/{id}/messages` return ordered `file_refs`, enriched attachment refs preserve image MIME/name/size/status after refresh, and extracted source text is absent.
- [ ] Step 6: Run `uv run pytest tests/test_chat_attachments.py tests/test_workspace_agent.py tests/test_conversation_workspace.py tests/test_workspace_service.py -q`; expect failures because the router, Message row, serializer, and orchestration currently discard `file_refs`.
- [ ] Step 7: Wire `req.message.file_refs` through the router only after workspace/org ownership resolution; reuse `resolve_workspace_path` and do not introduce a second path-normalization implementation.
- [ ] Step 8: Extend document preparation with workspace sources, shared chunk selection, and the same 12,000/48,000 character budget ledger used for uploads; upload attachments retain request order before workspace refs.
- [ ] Step 9: Persist only normalized relative `{path}` objects in `Message.file_refs`; enrich upload attachment refs before message creation so synchronous serialization performs no repository N+1 queries.
- [ ] Step 10: Run the Task 5 pytest command again; expect PASS.
- [ ] Step 11: Run `uv run ruff check app/api/schemas/chat.py app/api/routers/chat.py app/storage/models/message.py app/storage/repositories/message.py app/services/serializers.py app/orchestration/chat_stream.py app/orchestration/document_input.py tests/test_chat_attachments.py tests/test_workspace_agent.py tests/test_conversation_workspace.py tests/test_workspace_service.py`; expect no errors.
- [ ] Step 12: Commit only Task 5 files with message `fix(workspace): deliver file references to agent context`.

---

## Task 6: Align frontend attachment status and optimistic/replay rendering

**Files:**
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/business/AttachmentBubble.vue`
- Test: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/business/AttachmentBubble.spec.ts`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/stores/chat.ts`
- Test: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/stores/chat.spec.ts`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/views/ChatView.vue`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/workspace/WorkspaceShell.vue`
- Test: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/workspace/WorkspaceShell.spec.ts`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/mock/server.ts`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/progress.md`

**Interfaces:**
- Consumes: enriched `Message.attachments[]`, persisted `file_refs[]`, neutral `analysis_on_send`, and SSE error 60005 from backend Tasks 2–5.
- Produces: optimistic user messages containing full `AttachmentRef[]`, while outbound `message.attachments` remains UUID strings.
- Preserves: Provider frontend types and Settings UI exactly; no capability checkbox, tri-state selector, tooltip, or Provider request field is added.

- [ ] Step 1: Keep the existing untracked `AttachmentBubble.spec.ts` test that asserts no upload/analysis badges and no `/analysis` polling; add assertions that image refs render `<img>` after replay and document refs render filename/size without “待分析/已分析”.
- [ ] Step 2: Add chat-store tests changing `appendUserMessage(content, attachmentRefs, fileRefs?)`; assert full MIME/name/size/status survives the optimistic append and the API request still contains only attachment IDs.
- [ ] Step 3: Extend WorkspaceShell tests to assert its already-present full optimistic refs and `file_refs` survive a message-list refresh from the real backend shape.
- [ ] Step 4: Run `npm run test:unit -- src/components/business/AttachmentBubble.spec.ts src/stores/chat.spec.ts src/components/workspace/WorkspaceShell.spec.ts`; expect the AttachmentBubble and ChatView/store assertions to fail against current polling and ID-only optimistic state.
- [ ] Step 5: Remove AttachmentBubble analysis polling, badges, summary overlay, timer lifecycle, and `getAttachmentAnalysis` import; attachment cards display upload identity only because actual analysis occurs in the chat turn.
- [ ] Step 6: Change ChatView/store optimistic paths to pass `PendingAttachment[]` as display refs, matching the already-correct WorkspaceShell pattern; preserve failed-draft retry and the 10-source client guard.
- [ ] Step 7: Update mock message creation and message-list replay to return enriched attachment refs and `file_refs`; do not add or consume Provider capabilities.
- [ ] Step 8: Run `npm run typecheck`, `npm run lint:check`, and `npm run test:unit`; expect all to pass.
- [ ] Step 9: Run `npm run build`; copy generated `dist` into backend `frontend_dist` using the repository's existing frontend synchronization workflow, never by editing minified assets.
- [ ] Step 10: Update the frontend handoff board: mark the obsolete 2026-08-27 Provider-capabilities instruction as superseded by runtime capability negotiation, retain the open backend file-context item until Tasks 1–5 pass, and record frontend test/build results.
- [ ] Step 11: Commit only Task 6 frontend files with message `fix(chat): align attachment rendering with analysis-on-send`.

---

## Task 7: Run integration gates and update operational documentation

**Files:**
- Modify: `README.md`
- Modify: `progress.md`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/progress.md`
- Test: `tests/test_llm.py`
- Test: `tests/test_multimodal.py`
- Test: `tests/test_document_extraction.py`
- Test: `tests/test_document_input.py`
- Test: `tests/test_chat_attachments.py`
- Test: `tests/test_tasks_api.py`
- Test: `tests/test_workspace_agent.py`
- Test: `tests/test_conversation_workspace.py`
- Test: `tests/test_workspace_service.py`

**Interfaces:**
- Documents: capability precedence `endpoint metadata -> runtime cache -> positive catalog hint -> unknown real request`, exact cache TTLs, error classification, supported file formats, context budgets, and current-turn-only hydration.
- Documents: `/attachments/{id}/analysis` is upload preparation/extraction status and is not evidence that the active model analyzed the attachment.

- [ ] Step 1: Add one integration scenario with model name `glm-5.3-flash` and no metadata: upload PNG, capture the first model request containing the image block, return success, send a second PNG, and assert the positive cache avoids metadata discovery while still delivering the image.
- [ ] Step 2: Add a parallel rejection scenario: first request returns structured `vision_not_supported`, SSE emits 60005 once, second request is blocked before disk read with a clear unsupported note, and no pure-text retry occurs.
- [ ] Step 3: Add mixed-source scenario PNG + Markdown + PDF + DOCX + workspace code ref; assert image and bounded source-labelled text coexist in the same latest HumanMessage model copy, source order is deterministic, and persistence/checkpoints contain only lightweight refs.
- [ ] Step 4: Run `uv run pytest tests/test_llm.py tests/test_model_capabilities.py tests/test_multimodal.py tests/test_document_extraction.py tests/test_document_input.py tests/test_chat_attachments.py tests/test_tasks_api.py tests/test_workspace_agent.py tests/test_conversation_workspace.py tests/test_workspace_service.py -q`; expect PASS.
- [ ] Step 5: Run full backend gate `uv run pytest -q`; expect no failures and only explicitly gated environment skips.
- [ ] Step 6: Run `uv run ruff check .`; expect no errors.
- [ ] Step 7: Run frontend gates `npm run typecheck`, `npm run lint:check`, `npm run test:unit`, and `npm run build` in `C:/Users/Admin1/Desktop/Agent/FrontEnd`; expect all to pass.
- [ ] Step 8: Update README attachment examples and capability explanation; remove the claims that non-pattern models are known non-visual, images always return `no_vision_model`, and PDF/Office are metadata-only M4 seams.
- [ ] Step 9: Add backend progress evidence with exact test counts and commit IDs. In frontend `progress.md`, close the file-context handoff only after real-backend verification proves PNG and document nonce content reached the captured model input and refresh preserves cards.
- [ ] Step 10: Run `rg -n "no_vision_model|VLM 为 M4 接缝|llm_vision_declared.*判定|capabilities.*vision.*强制" README.md app tests C:/Users/Admin1/Desktop/Agent/FrontEnd/src C:/Users/Admin1/Desktop/Agent/FrontEnd/progress.md`; expect no active product logic or open handoff instruction to claim Provider/static-list gating. Historical completed plans may retain their original text.
- [ ] Step 11: Commit Task 7 documentation and final integration tests with message `docs(multimodal): document runtime capability negotiation`.

---

## Completion Criteria

- [ ] `glm-5.3-flash` or any other unknown model receives the user's first image instead of being rejected by a local name list.
- [ ] Successful image transport and explicit image rejection are cached with the exact endpoint/model/transport scope and TTLs; transient failures never poison the cache.
- [ ] No Provider backend/frontend contract or settings control is added for multimodal capability.
- [ ] TXT, Markdown, text/code workspace refs, text-bearing PDF, and DOCX content are visible to the model with source labels and exact budgets.
- [ ] `.doc`, scanned/no-text PDF, corrupt documents, unreadable sources, and model image rejection produce truthful, non-misleading messages.
- [ ] The upload UI never displays “当前部署无视觉模型（VLM 为 M4 接缝）” or claims that `ready` means the active model analyzed the file.
- [ ] Message replay preserves attachment MIME/name/size/status and ordered workspace `file_refs` without persisting image bytes or extracted document bodies.
- [ ] Backend and frontend full gates pass, and both progress ledgers contain the final evidence.
