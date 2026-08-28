# 进度账本 — plan: C:\Users\Admin1\Desktop\Agent\FrontEnd\docs\plans\2026-08-28-attachment-context-and-file-ref-fix.md

后端 agent 责任范围：Tasks 1–3；保持现有未提交改动，不触碰 FrontEnd 源码。

- Task 1: complete（schema/契约、40015 路径语义和目标测试；目标 pytest → PASS）
- Task 2: complete（TXT/Markdown/PDF/DOCX 抽取、工作区安全读取、来源选择与预算；目标 pytest → PASS）
- Task 3: complete（当前轮上下文注入、图片兼容、轻量附件/file_refs 持久化、checkpoint 正文隔离；目标 pytest → PASS）

## 验证记录

- `uv run pytest tests/test_chat_file_refs.py tests/test_chat_document_context.py tests/test_chat_attachments.py tests/test_attachments_api.py tests/test_workspace_service.py -q` → **55 passed, 2 skipped**
- `.venv\\Scripts\\ruff.exe check --no-cache app tests/test_chat_file_refs.py tests/test_chat_document_context.py` → **PASS**
- `git diff --check` → **PASS**
- 依赖锁定：`pypdf==6.16.2`、`python-docx==1.2.0`（`uv.lock` 已更新）

## 交接备注

- 工作区前端账本由前端 agent 维护；本文件是后端仓独立进度账本。
- 后端工作树含其它 agent 未提交改动；提交时只应纳入本计划相关文件，不能覆盖无关改动。
