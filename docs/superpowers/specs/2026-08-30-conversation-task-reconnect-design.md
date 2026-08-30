# 会话任务刷新重连与启动恢复设计

**状态：** `PROPOSED_FOR_APPROVAL`

**目标：** 在保持本地单机架构的前提下，让普通会话和工作区会话在切换、路由离开和浏览器刷新后能够发现原任务、回放持久业务轨迹并继续 live-tail；后端进程重启后不自动执行任务，而是把遗留任务安全收敛为可人工恢复或需重新发送的明确状态。

## 已批准的方向

本设计落实已确认的两个阶段：

1. 刷新自动找回会话 Task，并从持久事件恢复业务轨迹后继续订阅。
2. 后端启动时对账遗留任务，有精确且可验证的 LangGraph 游标才允许用户手动从断点继续。

不引入 Redis、独立 worker、多实例任务认领或服务重启后的自动执行；不持久化逐 token/thinking 增量；不承诺 shell、MCP、数据库或远程 API 副作用 exactly-once。

## 现状与缺口

- 前端 `useChatStream()` 已用 `Map<conversationId, ConvCtx>` 隔离同一组件生命周期内的多会话流，也已支持 `task_seq`、`after_seq` 回放和 live-tail。
- 上述 Map、当前会话 ID 和 Task ID 都只在浏览器内存中；页面刷新、ChatView 销毁或 WorkspaceShell `stopAll()` 后，前端失去 `conversation → task` 关系。
- 后端 Task 只在 `input.conversation_id` 中隐式关联会话；没有权威 active-task 查询，也没有阻止同一会话并发创建两个 `pending/running` Task。
- 普通 SSE 断开会触发 drain，当前后端进程存活时图会继续完成并落库。
- Task 事件已按 Task ID 写入 JSONL，但服务启动时只恢复 code checkpoint 与 rollback journal，不对账 `pending/running` Task。
- 现有恢复逻辑在没有显式 graph cursor 时查找 thread 级“最新失败 checkpoint”；共享 conversation thread 上这不足以证明它属于目标 Task。

## 架构决策

### 1. Task 显式绑定会话和恢复游标

Task 增加两个向后兼容字段：

```python
conversation_id: uuid.UUID | None = None
recovery_graph_checkpoint_id: str | None = None
```

- 新聊天 Task 创建时写 `conversation_id`；旧 `tasks.json` 读取时使用 dataclass 默认值，并在查询中回退 `input.conversation_id`、`pending_confirm.conversation_id`。
- `recovery_graph_checkpoint_id` 只能由启动对账器在验证 LangGraph checkpoint 存在后写入；客户端和 `error.details` 不能指定它。
- 不新增 `interrupted` Task status。进程重启遗留任务仍收敛为现有 `failed`，通过 `error.kind="process_restart"` 和 `error.recoverable` 区分，复用既有恢复 UI、终态判断和 `/recover` CAS。

### 2. 会话当前 Task 契约

新增：

```http
GET /api/v1/conversations/{conversation_id}/active-task
```

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "conversation_id": "uuid",
    "relation": "active | recoverable | null",
    "task": {
      "id": "uuid",
      "status": "running",
      "last_event_seq": 12,
      "started_at": "ISO-8601|null",
      "updated_at": "ISO-8601",
      "pending_confirm": null,
      "error": null
    }
  }
}
```

选择规则：

- `active`：最新 `pending/running/waiting_confirm` Task。
- `recoverable`：没有 active Task 时，最新 `failed && error.recoverable == true` Task。
- 否则 `task=null, relation=null`。
- 必须先验证 conversation owner；摘要不返回完整 `task.input`。
- 刷新后的客户端从 `after_seq=0` 回放，不能从 `last_event_seq` 开始，否则会跳过离开期间的轨迹。

### 3. 同会话单活约束

TaskService 增加 conversation 级进程锁，在同一个临界区内执行“查询 `pending/running/waiting_confirm` → 创建 Task → commit”。命中已有非终态 Task 时返回 `ERR_TASK_RUNNING (40901)`。

这是本地单实例约束，不伪装成分布式锁。它同时修复刷新发现请求尚未完成时、多个标签页或重复点击产生双 Task 的竞态。旧的 waiting-confirm 专用查询继续用于兼容，但 `/chat/stream` 统一走单活提交入口。

### 4. 前端 cold attach

`useChatStream` 增加显式的：

```ts
restoreConversation(conversationId: string): Promise<void>
detachConversation(conversationId: string): void
```

流程：

1. 选中会话后加载已持久化 Message，同时调用 active-task 查询。
2. 查询期间禁用 composer；以 generation/request token 防止 A→B 的迟到响应污染当前视图。
3. `task=null` 时回到 idle，以 Message 为事实源。
4. 找到 Task 时填入 `taskId/conversationId`；cold attach 的 `taskCursor=0`，通过现有 `/tasks/{id}/events` 先回放再 live-tail。
5. `task_seq` 去重继续使用现有逻辑；Message store 改为按 `message.id` upsert，避免已加载消息与回放的 `message/done` 重复。
6. `waiting_confirm` 恢复确认弹窗；`failed+recoverable` 显示手动恢复入口；`done` 竞态通过终态事件触发重新加载 Message/trajectory。
7. 本地 detach 只 abort 订阅，不调用后端 cancel，也不把状态伪装成 done；只有用户点击停止才调用 cancel。

不回放 token/thinking；离开期间只恢复 status、message、tool_call、tool_result、agent_switch、interrupt 和终态事件，最终正文以持久 Message 为准。

### 5. 刷新回到同一会话

会话选择写入 URL，而不是把 Task ID 写入 localStorage：

- 普通会话：`/chat?conversation=<conversation_id>`。
- 工作区会话：`/workspace/<workspace_id>?conversation=<conversation_id>`。

页面初始化时验证 owner 及 workspace 归属后选择该会话并 cold attach；无效、越权或不属于当前 workspace 的 ID 从 URL 移除并安全回到未选择状态。localStorage 不作为任务真相源。

### 6. 后端启动对账

在 FileStore、JsonFileSaver、graph 和 checkpoint crash recovery 初始化完成后、FastAPI 开始接收请求前运行 orphan Task 对账：

1. `done/cancelled/failed` 不变。
2. `waiting_confirm` 保持原状态，继续使用现有 TTL 和显式确认流程。
3. `pending` 标为 `failed + kind=process_restart + recoverable=false`；没有证据证明它已建立断点，不自动重发原输入。
4. `running` 聊天 Task：使用 `conversation_id + task.input.checkpoint_id` 调用 `get_run_bounds`，取该 code anchor 的 graph output，再用显式 `checkpoint_id` 读取验证。
5. `running` 独立后台 Task：其 thread 独占为 `task.id`，读取 latest tuple 后提取并再次显式验证 checkpoint ID。
6. 验证成功则持久化 `recovery_graph_checkpoint_id`，标记 `failed + recoverable=true`；失败则 `recoverable=false`。
7. 每个被收敛的 Task 只追加一次 `error` 业务事件；重复启动对账不得重复事件。

特殊完成窗口：如果聊天最终 assistant Message 已提交、但 Task 还停留在 running，则通过该 Task 的持久 `message_start.message_id` 验证最终 Message，直接补齐 Task done 和缺失的 done 事件，不要求用户恢复，也不生成重复 assistant Message。

### 7. 精确游标人工恢复

- `POST /tasks/{id}/recover` 继续保留幂等 key 和最多三次限制。
- `process_restart` 恢复必须把 Task 的 `recovery_graph_checkpoint_id` 显式传给 chat `retry_stream_events` 或后台 `recover_task_graph`。
- `stream_graph_events(initial=None)` 仅在 config 没有显式 `checkpoint_id` 时才允许调用旧的 `aget_failed_config`；LLM transport 恢复保持原行为。
- 恢复再次失败时，新错误覆盖旧错误；只有 `error.kind=process_restart` 才消费 restart cursor，防止陈旧游标污染后续 transport recovery。
- UI 在用户点击前明确提示：未完成节点可能重新执行，shell/MCP/数据库/远程 API 等外部副作用可能重复；系统不会在启动时自动恢复。

## 错误与兼容

- 新增稳定运行时错误码 `ERR_TASK_PROCESS_INTERRUPTED = 60009`。
- 有精确 cursor：`retryable=true, recoverable=true, kind=process_restart`。
- 无精确 cursor：`retryable=true, recoverable=false, kind=process_restart`，提示重新发送或新建任务。
- 旧 Task 无 `conversation_id/recovery_graph_checkpoint_id` 可加载；active 查询回退旧 JSON 字段。
- 旧前端忽略新增 Task 字段；现有 TaskStatus 联合无需新增枚举。
- active-task 查询与 Task 正好终态之间的竞态由事件端点的“先订阅后读历史”与终态 reload 收敛。

## 验收标准

1. 会话 A 执行时切到 B，A 不被 cancel；回到 A 能继续看到当前状态和后续事件。
2. A 执行期间刷新浏览器，URL 恢复 A，前端从 0 回放业务轨迹并继续 live-tail，不产生重复消息或第二个 Task。
3. waiting_confirm 刷新后重新出现确认弹窗。
4. 后端重启后，遗留 running Task 不自动运行；有精确 checkpoint 的显示“可从断点继续”，没有的明确要求重新发送。
5. 点击恢复只使用该 Task 持久化的精确 graph cursor，不会命中同 conversation 的旧轮或其它失败节点。
6. 最终 Message 已落库但 Task 未 done 的崩溃窗口自动收敛为 done，不生成重复回复。
7. token/thinking 不补发；持久消息、工具卡、状态与终态可恢复。
