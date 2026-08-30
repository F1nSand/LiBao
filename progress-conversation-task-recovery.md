# 进度账本 — plan: docs/plans/2026-08-30-conversation-task-reconnect-startup-recovery.md

> 当前执行范围：后端 Task 1–4；前端 Task 5–7 将在后端契约稳定后交接执行。

## 任务状态

- [completed] Task 1：Task 数据结构、60009 错误码和安全 active-task 摘要
- [completed] Task 2：会话当前 Task 查询与单会话单活提交
- [completed] Task 3：启动时 orphan Task 对账与精确 graph cursor
- [completed] Task 4：process_restart 精确游标人工恢复
- [pending] Task 5：前端 active-task API、URL 会话恢复和消息幂等
- [pending] Task 6：前端 cold attach、事件重建与本地 detach
- [pending] Task 7：工作区 URL 恢复与重启恢复风险提示
- [pending] Task 8：跨阶段集成验收、文档和交付 Gate

## 验证记录

- 执行开始：计划已获用户批准；按 `executor-debugger` 逐任务 TDD。
- Task 1：新增 `Task.conversation_id` / `recovery_graph_checkpoint_id`、`ERR_TASK_PROCESS_INTERRUPTED`、安全 `serialize_active_task`；补充旧 JSON 兼容与输入隔离测试。
- Task 1 验证：2 个定向 pytest 通过；Ruff（5 个修改文件）通过。
- Task 2：新增 `get_current_for_conversation`（含旧任务 input/pending_confirm 回退）、会话级锁与 `submit_for_conversation`，新增 `GET /conversations/{id}/active-task`，chat 提交改为单会话单活。
- Task 2 验证：`tests/test_conversation_tasks.py` 4 个通过；`test_chat_stream.py`、`test_chat_workspace_binding.py`、`test_tasks_api.py` 共 40 个通过；Ruff 通过。
- Task 3：新增启动 `reconcile_orphaned_tasks`，区分 pending/running、验证聊天 code anchor→graph output 或后台 task thread 精确 cursor；完成窗口可识别已落 assistant，所有对账均写入可回放 error/done 事件且不自动重跑。
- Task 3 验证：`tests/test_task_recovery.py` 3 个通过；Ruff 通过。
- Task 4：恢复图执行接受显式 `graph_checkpoint_id`；`stream_graph_events(initial=None)` 仅在未提供显式 cursor 时调用线程级失败解析；chat recovery 传递 `Task.recovery_graph_checkpoint_id`。
- Task 4 验证：`tests/test_llm_transport_retry.py` 与 `tests/test_task_recovery.py` 共 7 个通过；Ruff 通过。
- 后端全量回归：760 passed, 4 skipped；39 个既有弃用/依赖警告，无失败。
- 前端 Task 5–7：等待用户在本线程直接授权后执行（安全审查拒绝了转述授权，当前未修改 FrontEnd）。
- Review gate：发现并恢复基线 `tests/test_task_recovery.py` 的 3 个既有用例；随后该文件 6 个测试通过，Ruff 通过。
- 最终后端全量回归（恢复基线用例后）：763 passed, 4 skipped；39 个既有弃用/依赖警告，无失败。
