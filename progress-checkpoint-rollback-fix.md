# 进度账本 — plan: docs/plans/2026-08-30-checkpoint-rollback-fix-backend.md

> 本轮使用独立账本，保留仓库已有的历史 `progress.md` 不覆盖。

## 任务状态

- [complete] Task 1：统一 workspace identity 并兼容旧普通会话 manifest（commit `5918b28`；identity 定向 4 passed，restore 定向 3 passed，Ruff 通过）
- [complete] Task 2：切断 conversation-only 对文件工作区的依赖（commit `cbf9f4c`；restore/API 定向 6 passed，Ruff 通过）
- [complete] Task 3：固化会话 workspace 绑定（commit `cbe0577`；绑定定向 3 passed，Ruff 通过）
- [complete] Task 4：在首帧返回用户消息 checkpoint 锚点（commit `5c70ae1`；chat/interrupt/task-events 定向 21 passed，Ruff 通过）
- [complete] Task 5：绑定 restore preview 所属会话（commit `87ec4e6`；restore 定向 7 passed，Ruff 通过）
- [complete] Task 6：后端回归与交付门禁（最终文档/简化提交待归档）

## 验证记录

- Task 1：`uv run ... pytest tests/test_checkpoint_identity.py -q` → 4 passed；`tests/test_checkpoint_restore.py` → 3 passed。
- Task 2：conversation-only preview/execute、缺失 workspace API 与 code/both identity rejection → 6 passed；Ruff 通过。
- Task 3：`tests/test_chat_workspace_binding.py` → 3 passed；Ruff 通过。
- Task 4：`tests/test_chat_stream.py tests/test_interrupt_stream.py tests/test_task_events.py` → 21 passed / 2 warnings；Ruff 通过。
- Task 5：restore preview 跨会话与 operation-before 隔离 → 7 passed；Ruff 通过。
- Task 6：定向组合回归 36 passed / 2 warnings；全量 `pytest -q` → 719 passed / 4 skipped / 38 warnings；Ruff 通过；`python -m compileall -q app` 通过；`git diff --check` 通过。
- Review gate：人工 Review 未发现 Critical/High/Medium；Simplify 移除未使用的 restore `_identity` 私有包装和测试重复变量，并复跑 15 项定向测试 + Ruff 通过。
