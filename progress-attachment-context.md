# 进度账本 — plan: docs/plans/2026-08-28-attachment-context-and-file-ref-fix.md

执行状态：

- Task 1: complete (commit `fa31ec3`; tests `uv run pytest tests/test_model_capabilities.py -q` → PASS, 16 passed; ruff → PASS)
- Task 2: complete（未知模型 optimistic image delivery、明确拒绝 60005、瞬时错误不负缓存；`tests/test_multimodal.py` 32 passed；聊天/Task 附件回归通过）
- Task 3: complete（新增 `app/services/document_extraction.py`，图片分析改为 `analysis_on_send`；`tests/test_document_extraction.py` + `tests/test_attachments_api.py` 通过）
- Task 4: complete（复用既有 `document_context` 当前轮水合，并新增 `document_input` 兼容门面；文档正文 checkpoint 隔离回归通过）
- Task 5: complete（file_refs schema extra-forbid、工作区安全读取和附件展示元数据链路已落地；工作区每来源最多读取 1MiB；`tests/test_chat_file_refs.py`、workspace 回归通过）
- Task 6: complete（前端现有附件/工作区改动已通过 `npm run typecheck`、`npm run lint:check`、`npm run test:unit`：39 files / 206 tests、`npm run build`；构建产物已同步 `frontend_dist`）
- Task 7: complete（后端最终全量 `uv run pytest -q`：647 passed, 3 skipped；`uv run ruff check .`：PASS；前端 typecheck/lint/unit/build 全通过；重启本机 8000 后运行真实 `npm run test:e2e:real`：4 passed / 30.5s，含 file_refs 越界 40015、工作区 UI 与真实 LLM SSE。）

说明：`progress.md` 已是用户先前计划 `2026-08-28-code-review-remediation.md` 的账本，保留不覆盖；本文件是本计划的独立执行账本。
