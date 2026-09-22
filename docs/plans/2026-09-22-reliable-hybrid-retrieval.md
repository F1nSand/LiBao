# LiBao 可靠混合检索实施计划

**Goal:** 将 LiBao 的内存 BM25＋固定字符分块改造成基于 LanceDB 持久化 FTS、版本化 generation、结构/递归 token 分块和可验证降级策略的可靠混合检索系统。

**Architecture:** 保留 `index.json` 作为集合/文档可见性事实源，将其升级为 v2 manifest；在现有 `vectors.lance` 数据库中新建 `chunks_v2` 表，同时承载向量和 ICU FTS。每次索引写入一个不可见 generation，验证通过后原子切换 `active_generation`，旧代在切换完成后清理；检索先用 Lance 的 `active=true` 预过滤，再以 manifest 做最终可见性校验。旧数据通过可续跑旁路迁移复制已有向量，迁移完成前保留 legacy 回退，正常启动不再扫描全文重建 BM25。

**Approved design:** `docs/superpowers/specs/2026-09-22-reliable-hybrid-retrieval-design.md`

**Global Constraints:**

- 不引入 Elasticsearch、OpenSearch、Qdrant 或其他外部检索服务。
- LanceDB 版本保持 `>=0.37.1`；FTS 默认使用 `tokenizer_name="icu"`、`stem=False`、`remove_stop_words=False`。
- `POST /kb/search` 的 `hybrid={semantic,bm25}`、`top_k<=10`、命中列表结构和 `kb_search` Agent 工具保持向后兼容；`bm25` 继续作为词法通道的 API 名称。
- 新 generation 完整写入和验证前不得删除旧 active generation；首次索引失败为 `failed`，已有 active 的重索引失败仍保持旧版本可检索。
- 归档、软删除和集合删除必须先撤销 manifest 可见性，再进行 Lance 物理清理；清理失败不得导致文档重新可见。
- 正常启动、上传、归档和删除不得全量重建 BM25/FTS；`optimize()` 只能由维护阈值或后台任务触发。
- ICU 是默认中文/混合语言 tokenizer；Jieba 仅作为显式配置，缺少 Lance 语言模型文件时启动校验失败并回退 ICU。
- 默认分块策略为 `auto`（结构感知＋递归 token 限制）；`semantic` 只能由集合显式启用，失败时确定性回退 `auto` 并记录诊断。
- 旧 `vectors` 表、v1 `index.json` 和原文在迁移全量校验通过前不得删除或覆盖；回滚必须能继续使用 legacy 链路。
- 保留当前 UTF-8 txt/md 上传、20MB 上限、3 秒状态轮询及 `uploaded/chunking/indexing/indexed/failed/archived` 用户态状态。
- 当前工作区已有大量未提交修改；执行器只暂存本计划列出的文件，不执行 reset、checkout、clean、全量格式化或无关重写。

---

## Task 1: 固化基线、质量指标和现有缺陷回归样本

**Files:**

- Create: `apps/backend/app/evaluation/__init__.py`
- Create: `apps/backend/app/evaluation/kb_retrieval.py`
- Create: `apps/backend/tests/fixtures/kb_retrieval_golden.jsonl`
- Create: `apps/backend/tests/test_kb_retrieval_metrics.py`
- Modify: `apps/backend/tests/test_kb_api.py:79-205`
- Modify: `apps/backend/tests/test_kb_search.py:83-194`
- Modify: `apps/backend/tests/test_chunker.py`

**Interfaces:**

- Produce `RetrievalCase(query: str, relevant_chunk_ids: frozenset[str], category: str)`.
- Produce `RetrievalMetrics(recall_at_5: float, recall_at_10: float, mrr: float, ndcg_at_10: float, no_answer_false_positive_rate: float)`.
- Produce `evaluate_rankings(cases: Sequence[RetrievalCase], rankings: Mapping[str, Sequence[str]]) -> RetrievalMetrics`.
- Golden JSONL fields are exactly `id`, `query`, `category`, `relevant_chunk_ids`, `expect_no_answer`; categories include `zh_phrase`, `mixed_language`, `identifier`, `version`, `heading`, `semantic`, `no_answer`, and `archived_exclusion`.

- [ ] Step 1: Add metric unit tests with hand-calculated rankings: perfect ranking must return all `1.0`; one relevant item at rank 2 must return `mrr=0.5`; a no-answer case with one result must increment false-positive rate; duplicate chunk IDs must be counted once.
- [ ] Step 2: Run `uv run pytest tests/test_kb_retrieval_metrics.py -q` from `apps/backend`; expect import failure because the evaluation module does not exist.
- [ ] Step 3: Implement immutable metric dataclasses, JSONL loader, Recall@K, reciprocal rank, binary-relevance nDCG@10, and no-answer false-positive rate without network calls.
- [ ] Step 4: Add characterization tests for current contracts: blank query returns `[]`, `top_k` clamps to 10, numeric `hybrid` values behave as booleans, pure BM25 never calls embedding, rerank failure preserves RRF order, and archived content is excluded by the legacy BM25 corpus.
- [ ] Step 5: Add fixture cases containing Chinese phrases (`人工智能代理`), mixed queries (`MCP 工具 discovery`), identifiers (`create_fts_index`), versions (`v0.37.1`), heading-based questions, semantic paraphrases, no-answer queries, and archived-only terms.
- [ ] Step 6: Run `uv run pytest tests/test_kb_retrieval_metrics.py tests/test_kb_api.py tests/test_kb_search.py tests/test_chunker.py -q`; expect all baseline and metric tests to pass before storage changes.
- [ ] Step 7: Commit only these files with `test: establish hybrid retrieval baseline`.

## Task 2: 引入 index.json v2 manifest、索引字段和并发安全原子更新

**Files:**

- Create: `apps/backend/app/storage/kb/__init__.py`
- Create: `apps/backend/app/storage/kb/manifest.py`
- Create: `apps/backend/tests/test_kb_manifest.py`
- Modify: `apps/backend/app/storage/models/kb.py:12-47`
- Modify: `apps/backend/app/storage/repositories/kb.py:146-170,205-239,271-292`
- Modify: `apps/backend/app/services/serializers.py:172-203`

**Interfaces:**

- Add to `KbCollection`: `chunking_strategy: str = "auto"`, `fts_tokenizer: str = "icu"`.
- Add to `KbDocument`: `active_generation: str | None = None`, `building_generation: str | None = None`, `index_state: str = "idle"`, `chunking_version: str | None = None`, `retrieval_schema_version: int = 1`, `embedding_dimension: int | None = None`, `last_indexed_at: datetime | None = None`, `last_index_error: str | None = None`.
- Extend `KbChunk` with `generation: str`, `retrieval_text: str`, `section_path: tuple[str, ...]`, `start_offset: int`, `end_offset: int`, `token_count: int`, `chunking_strategy: str`; preserve `content` as the response text.
- Produce `empty_manifest() -> dict[str, Any]` with `version=2`, `documents={}`, `chunks={}`.
- Produce `normalize_manifest(raw: Mapping[str, Any]) -> dict[str, Any]`; v1 chunks become generation `legacy-v1`, but v1 input is never mutated.
- Produce `class KbManifestStore` with `load(collection_id)`, `save(collection_id, manifest)`, and `update(collection_id, mutate: Callable[[dict], None]) -> dict`; `update` holds one `asyncio.Lock` per collection across read-modify-write and persists through temp file＋`os.replace`. Before replacement, preserve the last valid file as `index.json.bak`; invalid primary JSON loads the backup and records `repair_required` instead of silently returning an empty manifest.
- Store chunks at `manifest["chunks"][document_id][generation]`; `active_chunks(manifest, document_id)` returns only the document's active generation.

- [ ] Step 1: Write `test_kb_manifest.py` tests for missing file defaults, v1 normalization, preservation of unknown document fields, generation lookup, atomic temp-file replacement, corrupted-primary recovery from `index.json.bak`, explicit failure when both copies are corrupt, and two concurrent `update()` calls retaining both changes.
- [ ] Step 2: Run `uv run pytest tests/test_kb_manifest.py -q`; expect module import failure.
- [ ] Step 3: Implement `KbManifestStore` and normalization helpers; move `_index_path`, `_load_index`, and `_save_index` behavior behind it while keeping repository compatibility wrappers during migration.
- [ ] Step 4: Extend the dataclasses and serializers. Existing document responses retain current fields; add optional `active_generation`, `index_state`, and `last_index_error` without removing `error` or changing progress values.
- [ ] Step 5: Update `create_collection`, `create_document`, `persist_document`, `list_chunks`, and `count_chunks` to use manifest atomic updates and active-generation lookup; do not change Lance or BM25 behavior in this task.
- [ ] Step 6: Run `uv run pytest tests/test_kb_manifest.py tests/test_kb_api.py tests/test_kb_search.py -q`; expect all tests to pass with v1 fixtures normalized in memory.
- [ ] Step 7: Commit with `refactor: add versioned KB manifests`.

## Task 3: 建立 chunks_v2 Lance 存储与持久化 ICU FTS

**Files:**

- Create: `apps/backend/app/storage/repositories/kb_lance.py`
- Create: `apps/backend/tests/test_kb_lance.py`
- Modify: `apps/backend/app/storage/repositories/kb.py:52-96,294-370`
- Modify: `apps/backend/app/storage/file/store.py:55-80`
- Modify: `apps/backend/tests/conftest.py:13-31`

**Interfaces:**

- Produce `LANCE_TABLE_NAME = "chunks_v2"`, `RETRIEVAL_SCHEMA_VERSION = 2`, `FTS_INDEX_NAME = "retrieval_text_fts_v1"`.
- `chunks_v2` fields: `chunk_id`, `document_id`, `collection_id`, `org_id`, `generation`, `chunk_index`, `content`, `retrieval_text`, `section_path`, `start_offset`, `end_offset`, `token_count`, `chunking_strategy`, `embedding_model`, `schema_version`, `active`, `created_at`, and `vector: float32[1024]`.
- Produce `RetrievalCandidate(chunk_id: UUID, document_id: UUID, collection_id: UUID, generation: str, content: str, channel_score: float)`.
- Produce `GenerationValidation(row_count: int, unique_chunk_count: int, vector_dimensions_valid: bool, empty_text_count: int)`.
- Produce `class KbLanceStore` with synchronous private Lance calls wrapped by public async methods:
  - `ensure_ready(tokenizer: str = "icu") -> None`
  - `write_generation(chunks: Sequence[KbChunk], *, active: bool = False) -> None`
  - `validate_generation(document_id: UUID, generation: str, expected_count: int) -> GenerationValidation`
  - `set_generation_active(document_id: UUID, generation: str, active: bool) -> None`
  - `delete_generation(document_id: UUID, generation: str) -> None`
  - `delete_document(document_id: UUID) -> None`
  - `vector_search(query_vector, collection_ids, limit) -> list[RetrievalCandidate]`
  - `fts_search(query, collection_ids, limit) -> list[RetrievalCandidate]`
  - `optimize() -> None`
  - `health() -> dict[str, Any]`.
- `ensure_ready` creates the FTS once with `create_fts_index("retrieval_text", replace=False, use_tantivy=False, tokenizer_name="icu", with_position=True, lower_case=True, stem=False, remove_stop_words=False, ascii_folding=True, name=FTS_INDEX_NAME)`; it does not call `replace=True` on normal startup.
- Both search methods use `active = true` and collection filters in Lance; manifest post-filtering remains mandatory in Task 8.

- [ ] Step 1: Write tests that create a temporary Lance database, call `ensure_ready()` twice, insert Chinese/mixed-language chunks, and prove `fts_search("人工智能代理")`, `fts_search("MCP discovery")`, and `fts_search("create_fts_index")` return expected chunks.
- [ ] Step 2: Add tests proving a newly appended generation is searchable without recreating the FTS index, inactive rows are excluded, vector search orders cosine neighbors, validation detects wrong counts/empty text, and deleting one generation leaves another generation intact.
- [ ] Step 3: Run `uv run pytest tests/test_kb_lance.py -q`; expect import failure.
- [ ] Step 4: Implement `KbLanceStore`; isolate module-level connection/table cache behind `reset_lance_store()` so the autouse temporary `FileStore` fixture cannot leak table handles across tests.
- [ ] Step 5: Change `KbRepository` to accept or construct `KbLanceStore` but retain legacy `_get_lance_table()` wrappers until migration cutover. Remove Lance schema creation from `kb.py` only after all existing tests use the new store.
- [ ] Step 6: Run `uv run pytest tests/test_kb_lance.py tests/test_kb_search.py tests/test_kb_api.py -q`; expect all tests to pass.
- [ ] Step 7: Commit with `feat: add persistent Lance FTS chunk store`.

## Task 4: 实现 generation 构建、验证、原子激活和失败回滚

**Files:**

- Create: `apps/backend/app/services/kb_generation.py`
- Create: `apps/backend/tests/test_kb_generation.py`
- Modify: `apps/backend/app/services/kb_pipeline.py:18-91`
- Modify: `apps/backend/app/services/kb.py:116-139`
- Modify: `apps/backend/app/storage/repositories/kb.py:229-329`

**Interfaces:**

- Produce `IndexBuildResult(document_id: UUID, generation: str, chunk_count: int, replaced_generation: str | None)`.
- Produce `DocumentIndexLocks.acquire(document_id: UUID) -> AsyncContextManager[None]`; reindex, archive, and delete use the same lock registry.
- Produce `class KbGenerationService`:
  - `build(document_id: UUID, *, embedder: EmbeddingService | None = None) -> IndexBuildResult`
  - `activate(document: KbDocument, generation: str, chunks: Sequence[KbChunk]) -> str | None`
  - `cleanup_generation(document_id: UUID, generation: str) -> None`.
- Build ordering is exact: write manifest `building_generation`/`building`; split and embed; write Lance rows with `active=False`; validate; set new Lance rows `active=True`; atomically write the new generation's chunk metadata, set manifest `active_generation`, and set document status `indexed` in one manifest update; set old Lance rows `active=False`; remove old manifest chunks and old Lance rows.
- Before manifest activation, a failure deletes only the new generation. With an existing active generation, restore document status `indexed`, preserve `active_generation`, set `last_index_error`, and clear `building_generation`; without an active generation, set status `failed` and populate `error`.
- After manifest activation, old-generation cleanup failure sets `index_state="cleanup_pending"`; new active data remains visible.

- [ ] Step 1: Write tests for successful first build and successful reindex, asserting exactly one manifest active generation and one set of active Lance rows.
- [ ] Step 2: Parameterize failure injection at split, embedding, Lance write, validation, manifest activation, and old-generation cleanup. Assert every pre-activation failure preserves old active chunks; cleanup failure produces `cleanup_pending` without reverting the new active generation.
- [ ] Step 3: Add concurrent tests for reindex/reindex serialization and a cancelled build clearing `building_generation` while retaining old active data.
- [ ] Step 4: Run `uv run pytest tests/test_kb_generation.py -q`; expect import failure and then failing old-pipeline assumptions.
- [ ] Step 5: Implement `KbGenerationService`; make `process_document()` a thin adapter that delegates to it and catches only errors already converted into persisted index state.
- [ ] Step 6: Change `KbService.reindex_document()` to start a new build without calling `delete_chunks()` or erasing the active generation. Keep the HTTP response unchanged.
- [ ] Step 7: Run `uv run pytest tests/test_kb_generation.py tests/test_kb_api.py tests/test_kb_search.py -q`; expect all generation and legacy API tests to pass.
- [ ] Step 8: Commit with `feat: make KB reindex generation-safe`.

## Task 5: 修复归档/删除一致性并加入启动恢复和后台维护

**Files:**

- Create: `apps/backend/app/services/kb_recovery.py`
- Create: `apps/backend/tests/test_kb_recovery.py`
- Modify: `apps/backend/app/services/kb.py:64-71,126-139`
- Modify: `apps/backend/app/storage/repositories/kb.py:229-268`
- Modify: `apps/backend/app/api/lifespan.py:23-66`
- Modify: `apps/backend/app/core/config.py:122-124`

**Interfaces:**

- Produce `RecoveryReport(scanned: int, repaired: int, cleanup_pending: int, repair_required: int, errors: tuple[str, ...])`.
- Produce `reconcile_kb_index() -> RecoveryReport`:
  - delete an unactivated `building_generation` from Lance and clear it from manifest;
  - retry old-generation deletion for `cleanup_pending`;
  - compare each active generation's manifest chunk count with Lance rows;
  - set `repair_required` when active rows are missing instead of fabricating data.
- Add settings: `kb_maintenance_interval_s: int = 3600`, `kb_optimize_min_mutations: int = 500`, `kb_recovery_enabled: bool = True`.
- Produce `kb_maintenance_loop(settings)` that retries cleanup and calls `KbLanceStore.optimize()` only when the mutation threshold is reached; cancellation is handled like existing lifespan loops.
- Archive ordering: acquire document lock, atomically set `status="archived"` and `active_generation=None`, then deactivate/delete all Lance generations. Delete ordering: atomically set `deleted_at` and clear active generation, then remove Lance rows and original markdown. Collection deletion repeats this per document before marking the collection deleted.

- [ ] Step 1: Write tests proving archive/delete become invisible immediately even when `delete_document()` in Lance raises; assert manifest visibility is revoked and `cleanup_pending` is persisted.
- [ ] Step 2: Write recovery tests for orphaned building generations, pending old generations, missing active rows, repeated idempotent runs, and one broken collection not preventing repair of another.
- [ ] Step 3: Write lifespan tests proving startup calls reconciliation but never calls legacy BM25 rebuild or Lance FTS replacement when v2 is healthy; maintenance cancellation must not leak tasks.
- [ ] Step 4: Run `uv run pytest tests/test_kb_recovery.py tests/test_kb_api.py -q`; expect new tests to fail.
- [ ] Step 5: Implement lifecycle ordering, `reconcile_kb_index()`, mutation counters, and the background maintenance loop; log collection/document IDs and error class but not document text.
- [ ] Step 6: Run `uv run pytest tests/test_kb_recovery.py tests/test_kb_generation.py tests/test_kb_api.py tests/test_kb_search.py -q`; expect all tests to pass.
- [ ] Step 7: Commit with `fix: reconcile KB index lifecycle`.

## Task 6: 实现 v1→v2 旁路迁移、断点续跑和 legacy 回退

**Files:**

- Create: `apps/backend/app/services/kb_migration.py`
- Create: `apps/backend/tests/test_kb_migration.py`
- Create: `apps/backend/tests/test_bootstrap.py`
- Modify: `apps/backend/app/core/bootstrap.py:1-55`
- Modify: `apps/backend/app/storage/file/store.py:55-80`
- Modify: `apps/backend/app/storage/repositories/bm25.py:1-81`
- Modify: `apps/backend/app/storage/repositories/kb.py:331-370`
- Modify: `apps/backend/app/core/config.py:122-128`

**Interfaces:**

- Migration ledger path: `<kb_root>/migration-v2.json`; write atomically and store `version`, `started_at`, `completed_at`, `documents`, `last_error`, and `legacy_fallback_required`.
- Produce `DocumentMigrationResult(document_id: UUID, status: Literal["migrated","skipped","reindex_required","failed"], chunk_count: int, reason: str | None)`.
- Produce `MigrationReport(total: int, migrated: int, skipped: int, reindex_required: int, failed: int, complete: bool)`.
- Produce `KbV2Migrator.migrate_all() -> MigrationReport` and `migrate_document(collection_id, document_id) -> DocumentMigrationResult`.
- Migration copies text from v1 manifest and vectors from legacy `vectors` table when the row count and 1024 dimensions match; it derives `retrieval_text`, writes generation `migrated-v1-<document_id>`, validates it, then atomically activates it. Missing rows or dimension mismatch yield `reindex_required`; no zero vectors are created.
- Extend `Runtime` with `kb_index_mode: Literal["v2","legacy_degraded"]` and `kb_migration: MigrationReport`.
- Normal startup with a complete ledger calls only `ensure_ready()` and recovery. Incomplete migration runs before application readiness. A migration exception enables `legacy_degraded`, performs the old BM25 rebuild once to preserve availability, exposes degraded health, and retries next startup; it never deletes the legacy table.
- Keep `rank-bm25` and `bm25.py` for one compatibility release, but remove all normal-path rebuild calls from insert, archive, delete, and healthy startup.

- [ ] Step 1: Write migration tests for successful vector copy, already-migrated idempotence, interruption after one document followed by resume, missing legacy Lance row, incompatible vector dimension, and rollback to untouched v1 files/table.
- [ ] Step 2: Add bootstrap tests with spies: completed migration must call zero `BM25Index.rebuild`; failed migration must select `legacy_degraded` and call one rebuild; subsequent healthy startup must not repeat migration writes.
- [ ] Step 3: Run `uv run pytest tests/test_kb_migration.py tests/test_bootstrap.py -q`; expect failures for missing migrator/runtime fields.
- [ ] Step 4: Implement the atomic ledger and migrator. Copy vectors directly; do not invoke `EmbeddingService` during compatible migration.
- [ ] Step 5: Integrate migration into `init_runtime()` before graph readiness, retain legacy query methods only behind `runtime.kb_index_mode == "legacy_degraded"`, and remove ordinary `store.bm25.rebuild(...)` calls.
- [ ] Step 6: Run `uv run pytest tests/test_kb_migration.py tests/test_bootstrap.py tests/test_bm25.py tests/test_kb_api.py -q`; expect migration and explicit legacy tests to pass.
- [ ] Step 7: Commit with `feat: migrate KB indexes to persistent FTS`.

## Task 7: 用结构感知＋递归 token 分块替换固定字符滑窗

**Files:**

- Modify: `apps/backend/pyproject.toml:5-25`
- Modify: `apps/backend/uv.lock`
- Replace: `apps/backend/app/services/chunker.py`
- Modify: `apps/backend/tests/test_chunker.py`
- Modify: `apps/backend/app/services/kb_generation.py`
- Modify: `apps/backend/app/storage/models/kb.py:16-47`

**Interfaces:**

- Add production dependency `tiktoken>=0.9.0`; use local encoding `cl100k_base` and record `tokenizer_id="cl100k_base"`. This is a deterministic conservative chunk budget, not a claim that it exactly matches Qwen's tokenizer.
- Produce `ChunkingOptions(strategy: Literal["auto","semantic"], max_tokens: int = 512, overlap_tokens: int = 64, min_chunk_tokens: int = 48, semantic_break_percentile: float = 90.0)`.
- Produce `ChunkSpan(content: str, retrieval_text: str, section_path: tuple[str, ...], start_offset: int, end_offset: int, token_count: int, strategy: str)`.
- Produce `async chunk_document(text: str, *, filename: str, content_type: str, options: ChunkingOptions, embedder: EmbeddingService | None = None) -> list[ChunkSpan]`.
- `auto` recognizes Markdown ATX headings, fenced code blocks, lists, blank-line paragraphs, Chinese/English sentence punctuation, whitespace, then token hard-split; it merges undersized adjacent spans only inside the same section.
- Overlap is applied only after token hard-split and is capped by `min(overlap_tokens, max_tokens // 4)`.
- `retrieval_text` is deterministic: `filename`, joined `section_path`, then `content`, each separated by `\n`; blank parts are omitted.
- `semantic` sentence-splits first, batches sentence embeddings, cuts where adjacent cosine distance is at or above the configured percentile, and finally applies the same recursive token bound. Any semantic embedding error logs a fallback reason and returns the exact `auto` result.

- [ ] Step 1: Add tests for Markdown heading isolation, fenced code preservation, Chinese and English sentence boundaries, token upper bounds, no mechanical overlap on natural blocks, controlled overlap on hard splits, small-block merging within but not across sections, offsets reconstructing source substrings, and deterministic retrieval text.
- [ ] Step 2: Add semantic tests with a fake embedder: a large topic-change distance creates a boundary; same-topic sentences stay together; embedding failure returns byte-for-byte identical auto chunks.
- [ ] Step 3: Run `uv run pytest tests/test_chunker.py -q`; expect failures against the character-window implementation.
- [ ] Step 4: Add `tiktoken`, regenerate `uv.lock`, implement `chunk_document`, and retain `chunk_text(text, chunk_size, overlap)` as a deprecated compatibility wrapper returning only `.content` until callers/tests are migrated.
- [ ] Step 5: Update generation building to persist every `ChunkSpan` field and call the embedder on chunk `content`, not `retrieval_text`; semantic sentence embeddings are used only for boundary selection.
- [ ] Step 6: Run `uv run pytest tests/test_chunker.py tests/test_kb_generation.py tests/test_kb_api.py -q`; expect all tests to pass.
- [ ] Step 7: Commit with `feat: add structure-aware token chunking`.

## Task 8: 拆分并强化混合召回、RRF、rerank 校验和诊断

**Files:**

- Create: `apps/backend/app/services/kb_retrieval.py`
- Create: `apps/backend/tests/test_kb_retrieval.py`
- Modify: `apps/backend/app/storage/repositories/kb.py:348-466`
- Modify: `apps/backend/app/services/kb.py:141-156`
- Modify: `apps/backend/app/tools/builtin/kb_search.py:1-74`
- Modify: `apps/backend/app/core/config.py:122-132`

**Interfaces:**

- Produce `ChannelDiagnostics(enabled: bool, succeeded: bool, hit_count: int, elapsed_ms: float, error_type: str | None)`.
- Produce `RetrievalDiagnostics(index_mode: str, tokenizer: str, semantic: ChannelDiagnostics, lexical: ChannelDiagnostics, rerank: ChannelDiagnostics, filtered_stale: int, final_path: str)`.
- Produce `HybridSearchResult(hits: list[dict[str, Any]], diagnostics: RetrievalDiagnostics)`.
- Produce `KbRetrievalService.search(org_id, collection_ids, query, top_k=5, hybrid=None, embedder=None, reranker=None) -> HybridSearchResult`.
- Add settings with existing defaults: `kb_channel_limit=50`, `kb_rrf_k=60`, `kb_rerank_candidates=20`, `kb_postfilter_overfetch=3`, `kb_postfilter_max_candidates=500`.
- Semantic embedding and lexical FTS execute concurrently with `asyncio.gather(return_exceptions=True)` when both are enabled. One failed channel degrades to the other; both enabled channels failing raises `AppError(ERR_INTERNAL, "知识库召回通道全部失败")`; both succeeding with no hits returns `[]`.
- RRF is exact `sum(1 / (kb_rrf_k + rank))` using one-based rank; ties sort by `chunk_id` for deterministic output.
- Candidate validity requires manifest status `indexed`, no `deleted_at`, and exact `candidate.generation == active_generation`. Lance `active=true` is only a prefilter. Over-fetch until enough valid candidates or the configured cap.
- Rerank output must contain unique integer indexes in range and at least one entry. Any duplicate, out-of-range, non-integer, timeout, HTTP error, or malformed response causes full deterministic RRF fallback. Valid but shorter output is filled from remaining RRF candidates without duplicates until `top_k`.
- `KbRepository.hybrid_search()` remains as a compatibility adapter returning `result.hits`; REST and Agent tool therefore share one implementation.

- [ ] Step 1: Write tests for concurrent channel start, exact RRF ordering/tie break, active-generation filtering, stale-row over-fetch, collection filtering, semantic-only, lexical-only, one-channel failure, both-channel failure, and both-success-empty.
- [ ] Step 2: Parameterize rerank tests for duplicate indexes, out-of-range indexes, non-integers, empty response, partial valid response, timeout, and normal reorder; assert malformed cases exactly match RRF order.
- [ ] Step 3: Add a test that archived content remains excluded when its Lance row is still `active=true`, proving manifest is authoritative.
- [ ] Step 4: Run `uv run pytest tests/test_kb_retrieval.py tests/test_kb_search.py tests/test_kb_search_tool.py -q`; expect failures before the service exists.
- [ ] Step 5: Implement retrieval orchestration and reduce `KbRepository` to persistence/query primitives plus compatibility adapters. Do not expose full document text in diagnostics or logs.
- [ ] Step 6: Update `KbService.search` and `kb_search_handler` to call the adapter; preserve current hit fields `chunk_id`, `text`, `score`, `rerank_score`, and `source`.
- [ ] Step 7: Run `uv run pytest tests/test_kb_retrieval.py tests/test_kb_search.py tests/test_kb_search_tool.py tests/test_rerank.py -q`; expect all tests to pass.
- [ ] Step 8: Commit with `feat: harden hybrid retrieval orchestration`.

## Task 9: 补齐配置、健康/调试 API、前端契约和知识库界面

**Files:**

- Modify: `apps/backend/app/api/schemas/kb.py:10-25`
- Modify: `apps/backend/app/api/routers/kb.py:29-155`
- Modify: `apps/backend/app/services/kb.py:30-156`
- Modify: `apps/backend/app/services/serializers.py:172-203`
- Modify: `apps/backend/app/api/routers/system.py:31-42`
- Modify: `apps/backend/tests/test_kb_api.py`
- Modify: `apps/backend/tests/test_system_health.py`
- Modify: `apps/frontend/src/types/api.ts:379-421`
- Modify: `apps/frontend/src/api/kb.ts:1-54`
- Modify: `apps/frontend/src/stores/kb.ts:1-144`
- Modify: `apps/frontend/src/stores/kb.spec.ts`
- Modify: `apps/frontend/src/views/KbView.vue`
- Modify: `apps/frontend/src/components/business/ChunkStatus.vue`
- Modify: `apps/frontend/src/components/business/ChunkStatus.spec.ts`
- Modify: `apps/frontend/src/mock/server.ts`
- Modify: `apps/frontend/src/mock/server.spec.ts`
- Modify: `apps/frontend/e2e/kb.spec.ts`
- Modify: `docs/api/contract.md`
- Regenerate: `contracts/openapi.json`

**Interfaces:**

- Extend `CreateCollectionRequest` with validated `chunking_strategy: Literal["auto","semantic"] = "auto"`, `fts_tokenizer: Literal["icu","jieba/default"] = "icu"`, `chunk_size: int` in `128..2048`, and `overlap: int` in `0..min(256, chunk_size//4)`.
- Preserve existing requests containing only `name`, `chunk_size`, and `overlap`.
- Add `GET /kb/health` returning `{status,index_mode,schema_version,fts_tokenizer,migration,recovery,pending_cleanup,last_optimize_at,last_error}`; status values are `ok`, `degraded`, or `error`.
- Add developer-only `POST /kb/search/debug` with the same body as `/kb/search`, returning `{hits,diagnostics}`. Keep `/kb/search` returning a bare hit list inside the standard envelope.
- Extend collection responses/types with `description`, `chunking_strategy`, and `fts_tokenizer`; extend document responses/types with optional `index_state`, `active_generation`, and `last_index_error`; extend `KbSearchHit` with the existing `source` field.
- Correct frontend `reindexDocument()` and `archiveDocument()` return type to `Promise<null>` because backend returns `ok()`.
- The collection dialog exposes an “高级索引设置” section for strategy, max tokens, overlap, and tokenizer. It defaults to `auto/512/64/icu` and validates overlap before submit.
- `ChunkStatus` displays old active availability during reindex as “重建中（旧版本可用）”; `cleanup_pending` is a non-blocking warning; `repair_required` is an error requiring reindex.

- [ ] Step 1: Add backend API tests for old create requests, validated advanced fields, invalid overlap, `/kb/health` healthy/degraded payloads, debug diagnostics, and unchanged `/kb/search` list response.
- [ ] Step 2: Run `uv run pytest tests/test_kb_api.py tests/test_system_health.py -q`; expect advanced contract tests to fail.
- [ ] Step 3: Implement schema validation, health/debug routes, serializers, and system health summary without returning document content in health data.
- [ ] Step 4: Add frontend API/store/component tests for advanced create payload, fixed null return types, health display, old-version-available status, cleanup warning, and repair error.
- [ ] Step 5: Run `npm run test:unit -- --run src/stores/kb.spec.ts src/components/business/ChunkStatus.spec.ts src/mock/server.spec.ts`; expect failures before UI/type changes.
- [ ] Step 6: Update types, API, Pinia store, `KbView`, `ChunkStatus`, and Mock routes. Keep existing upload polling at 3 seconds for `uploaded`, `chunking`, and `indexing`.
- [ ] Step 7: Regenerate `contracts/openapi.json` with `uv run python ../../scripts/export_openapi.py`, update `docs/api/contract.md`, and assert Authorization/config secrets are absent from generated artifacts.
- [ ] Step 8: Run backend API tests, frontend unit tests, `npm run typecheck`, and `npm run build`; then run `npm run test:e2e -- kb.spec.ts` and verify upload, reindex, archive, advanced collection creation, and status convergence.
- [ ] Step 9: Commit with `feat: expose reliable KB indexing controls`.

## Task 10: 增加离线评测、迁移演练和性能/运维命令

**Files:**

- Create: `scripts/eval_kb_retrieval.py`
- Create: `apps/backend/tests/test_kb_eval_cli.py`
- Create: `docs/operations/kb-index.md`
- Modify: `scripts/run_checks.py:14-38`
- Modify: `scripts/smoke_release.py`
- Modify: `README.md`

**Interfaces:**

- CLI: `uv run python ../../scripts/eval_kb_retrieval.py --fixture tests/fixtures/kb_retrieval_golden.jsonl --output <path> [--live]`.
- Offline mode evaluates supplied rankings from fixture field `observed_chunk_ids` and requires no API key. `--live` indexes fixture documents in a temporary KB root, uses configured embedding/rerank providers, records per-query stage latency, and never writes to the user's KB root.
- JSON report fields: `generated_at`, `mode`, `case_count`, `metrics`, `p50_ms`, `p95_ms`, `channel_failures`, `config`, and `cases`; config contains model names and index versions but no keys/base authorization headers.
- Exit non-zero when Recall@10 is below the committed baseline, any Chinese exact lexical golden case misses, or no-answer false-positive rate exceeds the baseline threshold stored in the fixture metadata.
- Operations doc includes data locations, first migration behavior, degraded fallback, health interpretation, forced reindex, optimize policy, backup, rollback, and removal criteria for legacy `rank_bm25`.

- [ ] Step 1: Write CLI tests for offline metric output, threshold failure exit code, secret redaction, temporary-root enforcement in live mode, and deterministic repeated reports excluding timestamp.
- [ ] Step 2: Run `uv run pytest tests/test_kb_eval_cli.py -q`; expect CLI import/path failure.
- [ ] Step 3: Implement CLI using Task 1 metrics and Task 8 diagnostics. Add a focused offline eval invocation to `scripts/run_checks.py` after backend pytest.
- [ ] Step 4: Extend release smoke to create a temporary collection, index a Chinese/mixed-language document, verify lexical and semantic search, archive it, verify both channels exclude it, restart runtime, and verify no BM25 rebuild marker appears.
- [ ] Step 5: Write `docs/operations/kb-index.md` with exact commands and recovery decision table; link it from README.
- [ ] Step 6: Run `uv run pytest tests/test_kb_eval_cli.py tests/test_kb_retrieval_metrics.py -q` and the offline CLI command; expect thresholds to pass.
- [ ] Step 7: Commit with `test: add KB retrieval quality gates`.

## Task 11: 全量验证、迁移回滚演练和收尾 Gate

**Files:**

- Create: `progress-reliable-hybrid-retrieval.md`
- Modify only when a failing check identifies a defect: files listed in Tasks 1–10.

**Interfaces:**

- Progress ledger records each task's commit hash, red/green commands, migration fixture, metric report, unresolved warnings, and rollback result.
- Required quality gate: migrated default path Recall@10 must not be below Task 1 baseline; all Chinese exact lexical golden cases pass; no archived/deleted fixture is returned; normal second startup performs zero BM25 rebuilds and zero FTS replacements.

- [ ] Step 1: Create the ledger before implementation starts and update it after every task; record the current dirty-worktree paths so unrelated user changes are never staged.
- [ ] Step 2: Run backend static/test gate from `apps/backend`: `uv run ruff check .` then `uv run pytest tests/`.
- [ ] Step 3: Run frontend gate from `apps/frontend`: `npm run lint:check`, `npm run typecheck`, `npm run build`, `npm run test:unit`, and `npm run test:e2e`.
- [ ] Step 4: Run `python scripts/run_checks.py` from repository root and retain the output summary in the ledger.
- [ ] Step 5: Create a copied temporary v1 KB fixture, interrupt migration after the first document, restart to completion, compare document/chunk counts, run golden search, then switch to the preserved legacy table and prove rollback search still works. Record paths and counts; do not use the real `~/.LiBao/kb` directory.
- [ ] Step 6: Exercise fault injection for embedding, Lance write, activation, cleanup, FTS, semantic channel, and rerank; verify the exact degradation/error contract and that no old active generation is lost.
- [ ] Step 7: Run `git diff --check`; inspect `git status --short`; verify no user KB data, `.env`, settings JSON, API key, Authorization header, Lance table, eval live corpus, or generated backup is staged.
- [ ] Step 8: Use `review-test-simplify` as the required closing gate. Resolve all P0/P1 findings, rerun the narrow failing tests after each fix, then rerun the full gates in Steps 2–4.
- [ ] Step 9: Commit the final integration and documentation changes with `feat: ship reliable hybrid retrieval`; do not push until the user explicitly requests it.

## Requirement Traceability

- Persistent/incremental BM25 without startup rebuild: Tasks 3, 5, 6.
- Semantic＋recursive/structure chunking: Task 7.
- Chinese tokenizer instead of per-character splitting: Tasks 3 and 7.
- Reliable upload/reindex/archive/delete: Tasks 2, 4, 5.
- Safe migration and rollback: Task 6 and Task 11.
- RRF/rerank/channel degradation correctness: Task 8.
- API/Web compatibility and observability: Task 9.
- Measurable retrieval quality: Tasks 1, 10, 11.
