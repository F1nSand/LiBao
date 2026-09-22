# 进度账本 — plan: docs/plans/2026-09-22-reliable-hybrid-retrieval.md

## Tasks

- [complete] Task 1: 固化基线、质量指标和现有缺陷回归样本 (commit `9f42dc1`; `uv run pytest tests/test_kb_retrieval_metrics.py tests/test_kb_search_contracts.py tests/test_kb_api.py tests/test_kb_search.py tests/test_chunker.py -q` → PASS, 35 passed; focused Ruff → PASS).
- [complete] Task 2: 引入 index.json v2 manifest、索引字段和并发安全原子更新 (commit `8eb6d20`; focused KB suite → PASS, 51 passed; Ruff → PASS).
- [complete] Task 3: 建立 chunks_v2 Lance 存储与持久化 ICU FTS (commit `da96d52`; KB regression suite → PASS, 60 passed; focused Ruff → PASS).
- [complete] Task 4: 实现 generation 构建、验证、原子激活和失败回滚 (commit `3e24702`; KB regression suite → PASS, 74 passed; focused Ruff → PASS).
- [complete] Task 5: 修复归档/删除一致性并加入启动恢复和后台维护 (KB regression → PASS, 87 passed; recovery suite → PASS, 13 passed; focused Ruff → PASS).
- [pending] Task 6: 实现 v1→v2 旁路迁移、断点续跑和 legacy 回退。
- [pending] Task 7: 用结构感知＋递归 token 分块替换固定字符滑窗。
- [pending] Task 8: 拆分并强化混合召回、RRF、rerank 校验和诊断。
- [pending] Task 9: 补齐配置、健康/调试 API、前端契约和知识库界面。
- [pending] Task 10: 增加离线评测、迁移演练和性能/运维命令。
- [pending] Task 11: 全量验证、迁移回滚演练和收尾 Gate。

## Safety notes

- Existing root `progress.md` belongs to a different plan and is left untouched.
- Worktree was already dirty before implementation; do not stage unrelated hunks or reset/checkout/clean files.
- Only files explicitly listed in the approved implementation plan may be modified for this task.

## Verification log

- Initial diff audit found a heavily dirty user worktree; only scoped files are staged per task.
- Task 1 red/green: expected missing-module failure, then focused suite PASS (35 passed); Ruff PASS; commit `9f42dc1`.
- Task 2 red/green: expected missing-manifest-module failure, then focused KB suite PASS (51 passed); Ruff PASS; commit `8eb6d20`. Windows CRLF check used `core.whitespace=cr-at-eol` to treat blank-line CRLF as line endings.
- Task 3 red/green: expected missing-Lance-store-module failure. Pinned LanceDB 0.37.1 rejected legacy `tokenizer_name="icu"`; switched to official `FTS(base_tokenizer="icu")` via `create_index`, then Chinese subword, mixed-language, identifier, vector/FTS filtering, generation deletion, and restart/concurrent initialization tests passed. Enforced non-null 1024D vectors at ingestion because Lance fills null vector values. KB suite PASS (60 passed); Ruff PASS; commit `da96d52`.
- Task 4 red/green: expected missing-generation-module failure; added generation rollback/activation fault injection, cancellation, reindex serialization, shared lifecycle lock, and v1 legacy preservation tests. KB suite PASS (74 passed); Ruff PASS; commit `3e24702`.
- Task 5 red/green: added archive/delete visibility revocation before cleanup, startup reconciliation, retryable orphan/pending cleanup, healthy-v2 startup guard against BM25 rebuild/FTS reinitialization, and thresholded Lance optimize. Focused recovery suite PASS (13 passed); KB regression suite PASS (87 passed); focused Ruff PASS. Manual code review found no remaining findings; desktop `/verify`, `/code-review`, and `/simplify` commands were not exposed as callable tools, so the affected end-to-end API/lifecycle paths were validated through pytest.
