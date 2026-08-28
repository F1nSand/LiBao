# 进度账本 — plan: C:\Users\Admin1\Desktop\Agent\FrontEnd\docs\plans\2026-08-28-attachment-context-and-file-ref-fix.md

后端 agent 责任范围：Tasks 1–3；保持现有未提交改动，不触碰 FrontEnd 源码。

- Task 1: complete（schema/契约、40015 路径语义和目标测试；目标 pytest → PASS）
- Task 2: complete（TXT/Markdown/PDF/DOCX 抽取、工作区安全读取、来源选择与预算；目标 pytest → PASS）
- Task 3: complete（当前轮上下文注入、图片兼容、轻量附件/file_refs 持久化、checkpoint 正文隔离；目标 pytest → PASS）

## 增量修复（review gate）

- 当前轮 hydrate：`document_ref` 增加 opaque `ref_id`；历史相同 attachment/path 不再复用正文。
- interrupt/resume：SSE 与 JSON resume 从 task input 重新读取文档，按原 ref_id 绑定；无上下文时将旧 ref 安全降级为 omission。
- 解析缓存：`extractor_version` + `extraction_strategy` 版本标记；旧 ready 缓存强制重抽。
- 工作区文件：读取前二次 realpath/普通文件校验，POSIX 尝试 `O_NOFOLLOW`。
- 共享契约同步：`C:\Users\Admin1\Desktop\Agent\docs\02-frontend-design.md` 的 §5.3.2/§8.3（及 AttachmentBubble 组件说明）改为只展示文件身份，解析状态仅后端内部使用。

## 验证记录

- `uv run pytest tests/test_chat_file_refs.py tests/test_chat_document_context.py tests/test_chat_attachments.py tests/test_attachments_api.py tests/test_workspace_service.py -q` → **55 passed, 2 skipped**
- `.venv\\Scripts\\ruff.exe check --no-cache app tests/test_chat_file_refs.py tests/test_chat_document_context.py` → **PASS**
- `git diff --check` → **PASS**
- `uv run pytest tests/test_chat_document_context.py tests/test_chat_file_refs.py tests/test_attachments_api.py tests/test_interrupt_stream.py -q` → **29 passed, 1 skipped**
- `.venv\\Scripts\\ruff.exe check --no-cache app/orchestration/document_context.py app/orchestration/chat_stream.py app/orchestration/task_run.py app/services/workspace.py app/services/attachment.py app/storage/attachment_analysis.py tests/test_chat_document_context.py tests/test_chat_file_refs.py tests/test_attachments_api.py tests/test_interrupt_stream.py` → **PASS**
- 依赖锁定：`pypdf==6.16.2`、`python-docx==1.2.0`（`uv.lock` 已更新）

## 交接备注

- 工作区前端账本由前端 agent 维护；本文件是后端仓独立进度账本。
- 后端工作树含其它 agent 未提交改动；提交时只应纳入本计划相关文件，不能覆盖无关改动。
