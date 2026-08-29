# 前端执行账本 — interrupt/resume recovery Task 3

来源计划：`C:/Users/Admin1/Desktop/Agent/docs/plans/2026-08-29-interrupt-resume-recovery.md`

## 进度

- [x] SSE 请求错误结构化：新增 `SseRequestError`，解析 HTTP/REST 错误信封，不将 REST envelope 冒充 SSE 事件。
- [x] 任务对账 API：新增 `getTaskStatus(taskId)`。
- [x] 中断确认乐观事务：`resuming`、`confirming`、resume snapshot、工具卡即时转 running、ack 接受、HTTP 回滚、网络断线任务对账。
- [x] 实时活动 reducer：thinking/tool/token/agent switch/status/done/error 去重、按会话隔离、最多 50 条。
- [x] UI：AgentRunStatus 动态文案与动效、InterruptConfirmDialog 防重复提交。
- [x] 回归调整（2026-08-29）：按用户要求删除 `LiveRunTrace` 实时执行区及 ChatView、WorkspaceShell、TrajectoryPanel 的可见接入；中断确认事务与顶部状态保留。
- [x] ChatView、WorkspaceShell、TrajectoryPanel 接入实时区；持久轨迹与实时活动分区，终态刷新后隐藏实时区。
- [x] 定向 Vitest：6 files / 31 tests passed；全量 Vitest：43 files / 223 tests passed（新增 TrajectoryPanel 定向测试后总计 224 tests）；`npm run typecheck` passed；`npm run lint:check` passed（3 个既有 any warning）。
- [x] `npm run build` passed；仅有依赖包 Rollup PURE 注释提示，无构建错误。

## 待联调

- [ ] 后端 Task 2/5 与真实 SSE ack、`GET /tasks/{id}`、真实 E2E 闭环仍需后端 agent 完成后联调。
- [ ] 前端 full `npm run test:unit`、`npm run build` 留待后端交接合并后门禁统一执行。
