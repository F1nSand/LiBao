# API 与 SSE 契约

基础地址为 `/api/v1`，REST 响应使用统一信封：成功时 `code=0`，失败时返回错误码、消息和可选 `trace_id`。前端 API 类型位于 `apps/frontend/src/types`，后端路由和 schema 位于 `apps/backend/app/api`。

聊天和任务流使用 SSE。事件至少包含单调递增的 `seq`，典型顺序为：

```text
message_start → token* → tool_call/tool_result → status → done 或 error
```

任务事件支持回放、`after_seq` 和 `Last-Event-ID`。中断/恢复、取消、附件、工作区引用和 checkpoint 回滚必须同时更新后端 schema、前端类型、Mock 和对应 E2E。

`contracts/openapi.json` 是 REST 契约快照；生成后若发生变化，必须在同一变更中更新前端消费代码和文档。
