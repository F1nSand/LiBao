# 进度账本 — plan: docs/plans/2026-08-30-checkpoint-rollback-correctness-backend.md

> 本账本专属于 checkpoint rollback correctness 后端计划；保留仓库既有 `progress.md`，不覆盖其他计划记录。

## 任务状态

- [complete] Task 1：修正消息 branch 的“空 head”表达（commit `3c447c7`；`tests/test_conversation_service.py` → 3 passed；checkpoint/API/trajectory 回归 → 9 passed；Ruff 通过）
- [complete] Task 2：记录并消费真实 LangGraph parent/output cursor（commit `52f52ad`；saver/chat/restore 回归 → 42 passed；Ruff、compileall 通过）
- [complete] Task 3：实现目标用户消息撤回和权威草稿响应（commit `69c2795`；checkpoint restore → 10 passed；Ruff、compileall 通过）
- [complete] Task 4：绑定 Preview 的模式、目标和精确文件计划（commit `ac1e1c5`；checkpoint/API/restore → 45 passed；Ruff、compileall 通过）
- [complete] Task 5：将文件恢复和逆恢复改成 Durable WAL（commit `f26d131`；WAL/store/restore → 22 passed；Ruff、compileall 通过）
- [complete] Task 6：准确表达写入、删除和 finalize 后状态（commit `577dad9`；mutation/store/restore/附件 → 37 passed, 1 skipped；Ruff、compileall 通过）
- [complete] Task 7：旧会话与 v1 Manifest 的安全兼容（commit `45ae379`；兼容/restore/WAL/API → 32 passed；Ruff、compileall 通过）
- [complete] Task 8：端到端回归与交付 Gate（commits `0ad8b8a`, `eea1112`, `1e864ee`, `9fb1b3b`；全量 pytest 748 passed, 4 skipped；Ruff、compileall、diff check 通过）
- [complete] 422 兼容性跟进：前端使用不透明字符串 `client_request_id`，旧静态 bundle 缺少 execute 的新字段；schema 已支持有界字符串、preview 默认 request id、execute 兼容缺省值，同时保留 v2 请求的 mode/request-id 严格校验（本次修复提交后补充 commit hash；定向 2 passed，全量 749 passed, 4 skipped；Ruff、compileall、diff check 通过）。

## 验证记录

- Task 8 定向回归：`.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_checkpoint_restore.py tests/test_checkpoint_api.py tests/test_chat_stream.py tests/test_interrupt_stream.py tests/test_code_checkpoint_store.py` → 46 passed。
- Task 8 新增游标边界回归：`.\\.venv\\Scripts\\python.exe -m pytest -q tests/test_conversation_service.py tests/test_chat_stream.py::test_empty_message_cursor_does_not_resurrect_legacy_history` → 5 passed。
- 全量测试（修复前）：`.\\.venv\\Scripts\\python.exe -m pytest -q` → 744 passed, 4 skipped。
- 全量测试（最终）：`.\\.venv\\Scripts\\python.exe -m pytest -q` → 748 passed, 4 skipped, 38 warnings。
- 静态检查：`.\\.venv\\Scripts\\ruff.exe check app tests`、`.\\.venv\\Scripts\\python.exe -m compileall -q app`、`git diff --check` → PASS。
- 内置 `verify`、`/code-review`、`mattpocock-skills:code-review`、`/simplify` 工具未在当前运行时暴露；以定向/全量行为测试、静态检查及人工安全/规范审查完成等价 gate。
- WAL recovery hardening：先以失败测试复现“after_cursor 已持久化但 applying 状态被误判 failed_partial”，修复后新增测试通过；恢复过程不触碰工作区字节。
- 422 根因：`CheckpointRestorePreviewRequest` 原先把前端 opaque token 错误声明为 UUID，`RestoreExecuteRequest` 也把旧 bundle 不会发送的 `expected_mode/client_request_id` 声明为必填；已补失败测试并修复为字符串兼容契约。
