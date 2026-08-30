# API 增量契约：长任务流恢复

本文记录长模型流的断线与断点恢复约定。它与模型上下文窗口无关：`LLM_STREAM_CHUNK_TIMEOUT_S` 只表示相邻流块允许的最长空闲时间，默认 300 秒；未知模型不会被本地硬编码成 256K 或 1M 窗口。

## 任务错误

`GET /tasks/{id}` 和任务事件中的 `error` 使用结构化对象：

```json
{
  "code": 60008,
  "message": "模型流式连接中断，可从最近断点继续",
  "kind": "llm_transport",
  "retryable": true,
  "recoverable": true,
  "details": {
    "model": "glm-5.3-flash",
    "chunks_received": 4948,
    "elapsed_ms": 120000,
    "last_chunk_age_ms": 120000,
    "context_metrics": {"estimated": true, "estimated_prompt_tokens": 12000}
  }
}
```

`details` 只包含脱敏的模型、计数、耗时和估算指标，不包含提示词、密钥、图片 base64 或文档正文。

## 任务事件游标

`GET /tasks/{id}/events?after_seq=N` 先回放已持久化的业务边界事件，再订阅后续事件。也可发送 `Last-Event-ID: task_evt_<N>`。SSE envelope 仍有连接内 `seq`，并额外提供跨连接单调的 `task_seq`：

```json
{"id":"task_evt_8","type":"tool_result","seq":2,"task_seq":8,"payload":{}}
```

持久化事件类型包括 `message_start`、`model_retry`、`status`、`message`、`tool_call`、`tool_result`、`agent_switch`、`interrupt`、`done`、`error`、`cancelled`。`token`/`thinking` 仅存在于当前 SSE 连接，不推进任务游标；终态后应重新加载会话消息和轨迹。

普通 `/chat/stream` 的首个 `message_start` 在用户消息成功持久化后携带可选回滚锚点：

```json
{
  "type": "message_start",
  "payload": {
    "message_id": "<assistant-message-uuid>",
    "agent_id": "<agent-uuid>",
    "conversation_id": "<conversation-uuid>",
    "task_id": "<task-uuid-or-null>",
    "user_message_id": "<persisted-user-message-uuid>",
    "checkpoint_id": "<code-checkpoint-uuid>"
  }
}
```

`message_id` 始终表示 assistant 消息；`user_message_id` 与 `checkpoint_id` 分别指向本轮真实用户消息和其 checkpoint。任务事件回放复用同一 payload；resume/恢复专用首帧可以省略这两个字段，旧客户端仍应按可选字段兼容。

## 从断点继续

对 `failed` 且 `error.recoverable=true` 的任务：

```http
POST /tasks/{id}/recover
Content-Type: application/json
Accept: text/event-stream
```

```json
{"idempotency_key":"recover-20260829-01"}
```

聊天任务在存在 `input.conversation_id` 时返回 SSE；后台任务返回 `{task_id,status:"running"}` 并在后台执行。恢复使用同一 task/thread 和显式失败 checkpoint，`initial=None`，不会重发用户输入，也不会重复已完成工具副作用。相同运行中的幂等键不会启动第二个 producer，单任务最多手动恢复 3 次。

模型传输错误会在同一流内自动重试一次，并发送：

```json
{"type":"model_retry","payload":{"attempt":2,"max_attempts":2,"reset_partial":true}}
```

前端应清除未封口的 partial 文本，保留已落库的工具轮和消息；断线后不得再次 POST 原始 `/chat/stream`。
