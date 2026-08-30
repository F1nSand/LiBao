# 进度账本 — plan: docs/plans/2026-08-30-message-checkpoint-rollback.md

## Tasks

- [completed] Task 1: 建立会话隔离 Blob/Manifest 存储 — commit 55dbf68; `uv run --cache-dir .uv-cache --python .venv\\Scripts\\python.exe --no-sync pytest tests/test_code_checkpoint_store.py -q` (5 passed); targeted Ruff passed
- [completed] Task 2: 将用户消息、活动分支与 LangGraph head 绑定 — message checkpoint_id/history_parent_id + active cursor; chat/resume paths covered by existing stream tests
- [completed] Task 3: 统一 AI 工作区文件 Mutation Gateway — direct write/edit/undo, workspace skill and GitHub cache; external/shell/memory excluded
- [completed] Task 4: 实现 Preview、三模式恢复和可逆 Operation — diff preview, conflict skip, operation-before preview
- [completed] Task 5: 暴露 API 并整合清理生命周期 — checkpoint list/preview/restore routes, startup interrupted recovery, 30-day TTL
- [completed] Task 6: 前端消息入口、预览弹窗与历史切换 — hover action, 3-mode dialog, diff/warning display, mock contract
- [completed] Task 7: 回归、构建同步与交付 Gate — full backend/frontend verification completed

## Verification ledger

- Backend: full `pytest -q` 706 passed, 4 skipped; targeted checkpoint/stream/file suites also passed; historical node switching regression 3 passed.
- Backend Ruff and `python -m compileall -q app`: passed.
- Frontend: `npm run typecheck`, `npm run build`, serial `npx vitest run --maxWorkers=1 --minWorkers=1` 256 passed; ESLint clean except 2 pre-existing `any` warnings in mock server.
- Commits: backend `55dbf68`, `849f69c`, `37e890a`, `54afe70`; frontend `e95686a`.
