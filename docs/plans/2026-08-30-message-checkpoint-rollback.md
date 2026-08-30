# Claude Code 风格消息级 Checkpoint 回滚实施计划

**Goal:** 为当前 Agent 增加以用户消息为锚点、只追踪 AI 直接文件工具、支持代码/对话/两者三种恢复模式且回滚自身可撤销的会话级 checkpoint 系统。

**Architecture:** 新建独立于 LangGraph 运行断点的代码 checkpoint 域。每条用户消息先落空 manifest；受支持的 AI 文件工具通过统一 mutation gateway 在真实写入前把文件完整 bytes 写入会话隔离的 SHA-256 blob store，再执行原子 mutation。消息日志继续不可变追加，通过活动 message/graph head 形成可逆分支；每次恢复先生成 diff preview，确认后写 rollback WAL 并切换活动状态。

**Global Constraints:**

- 每条新用户消息绑定一个 checkpoint；本轮无文件修改也保留空 checkpoint。
- 同轮同一路径只保存第一次修改前的完整原文；不以 diff 作为主存储。
- Blob 按 SHA-256 在单会话内复用，文本和二进制统一按 bytes 存储。
- 仅追踪 AI 通过声明为工作区文件 mutation 的直接工具产生的修改。
- Shell、脚本、数据库、MCP/远程服务、用户手动编辑、记忆和知识库均不快照、不回滚。
- 手动或其他会话改动导致 hash 冲突时跳过该文件，继续恢复其余文件，绝不强制覆盖。
- AI 正在运行时先取消并等待终态，再重新生成 preview。
- 默认 checkpoint 保留 30 天，可配置；长会话 checkpoint 分页不在本期。
- 前端源码只修改兄弟仓库 `C:/Users/Admin1/Desktop/Agent/FrontEnd`；`frontend_dist` 只能由构建产物同步生成。

---

## 1. 数据结构和磁盘布局

### 1.1 核心类型

```python
RollbackMode = Literal["code_only", "conversation_only", "both"]

CheckpointStatus = Literal[
    "open",         # AI 仍可能继续修改
    "sealed",       # 正常完成、取消或受控失败
    "interrupted",  # 重启发现未封口，仍可恢复
    "expired",
]

@dataclass
class FileVersionRef:
    exists: bool
    blob_sha256: str | None
    size_bytes: int
    content_kind: Literal["text", "binary"]

@dataclass
class FileMutationRecord:
    path: str
    before: FileVersionRef
    planned_after_sha256: str | None
    final_after_sha256: str | None
    tool_call_ids: list[str]
    status: Literal["prepared", "applied", "failed"]

@dataclass
class CodeCheckpoint:
    id: uuid.UUID
    conversation_id: uuid.UUID
    user_message_id: uuid.UUID
    workspace_identity: str
    anchor_message_head_id: uuid.UUID
    graph_input_checkpoint_id: str | None
    status: CheckpointStatus
    files: dict[str, FileMutationRecord]
    created_at: datetime
    sealed_at: datetime | None

@dataclass
class ConversationCursor:
    active_message_head_id: uuid.UUID | None
    active_graph_checkpoint_id: str | None
    active_code_node_id: uuid.UUID | None
    history_revision: int

@dataclass
class RollbackOperation:
    id: uuid.UUID
    conversation_id: uuid.UUID
    target_checkpoint_id: uuid.UUID
    mode: RollbackMode
    before_cursor: ConversationCursor
    after_cursor: ConversationCursor | None
    undo_files: dict[str, FileVersionRef]
    file_results: list[FileRestoreResult]
    status: Literal["prepared", "completed", "partial", "failed_partial"]
    created_at: datetime
```

### 1.2 消息和会话字段

- `Message.checkpoint_id: uuid.UUID | None`：仅新用户消息有值。
- `Message.history_parent_id: uuid.UUID | None`：活动对话分支中的前一条消息。
- 保留现有 `Message.parent_id`，继续表示 assistant round 对应的用户消息。
- `Conversation.active_message_head_id: uuid.UUID | None`。
- `Conversation.active_graph_checkpoint_id: str | None`。
- `Conversation.active_code_node_id: uuid.UUID | None`。
- `Conversation.history_revision: int = 0`。

### 1.3 会话隔离存储

```text
~/.LiBao/code-checkpoints/<conversation_id>/
  index.json
  manifests/<checkpoint_id>.json
  operations/<operation_id>.json
  blobs/sha256/<hash前两位>/<完整sha256>
```

- Blob 不可变并以原始 bytes 写入；同一会话相同内容只存一份。
- manifest、operation、index 均使用同目录临时文件加 `os.replace` 原子更新。
- `index.json` 保存 checkpoint/operation 顺序、当前 cursor、revision 和 `last_active_at`。
- 旧消息不补造代码快照；前端对其隐藏回滚入口或显示“此消息早于 checkpoint 功能”。
- 逻辑对话截断不删除 JSONL；不可见未来分支只从活动 head 脱离，直到会话级 GC。

---

## 2. 后端 API 契约

### 2.1 消息列表扩展

`GET /conversations/{conversation_id}/messages`

用户消息增加：

```json
{
  "checkpoint": {
    "id": "uuid",
    "status": "sealed",
    "changed_file_count": 3,
    "can_restore_code": true,
    "can_restore_conversation": true
  }
}
```

### 2.2 Checkpoint/操作历史

`GET /conversations/{conversation_id}/checkpoints`

- 本期一次返回全部用户锚点和 rollback operation，不分页。
- 返回 `current_state_id`、当前 cursor，以及隐藏分支中的历史锚点。
- 用户消息锚点和 rollback operation 使用区分明确的 `kind` 字段。

### 2.3 预览

`POST /conversations/{conversation_id}/restore-previews`

恢复到用户 checkpoint：

```json
{
  "target": {"type": "checkpoint", "id": "checkpoint-uuid"},
  "mode": "both"
}
```

撤销某次 rollback：

```json
{
  "target": {"type": "rollback_operation_before", "id": "operation-uuid"}
}
```

响应固定包含：

- `preview_id`、`mode`、`target_message_id`、`expires_at`。
- `conversation.truncate_after_message_id` 和 `hidden_message_count`。
- 文件项的 `path/action/content_kind/current_sha256/target_sha256/current_size/target_size`。
- 文本文件的 unified diff、`diff_truncated`；二进制文件不返回文本内容。
- `conflict` 和明确原因。
- 固定限制提示：shell/脚本、数据库、MCP/远程服务、手动编辑、记忆和知识库不回滚。

Diff 规则：仅两侧均为无 NUL 的有效 UTF-8 且单侧不超过 1 MiB 时生成，保留 3 行上下文，每文件响应最多 200 KiB；超限标记截断。

### 2.4 确认执行

`POST /conversations/{conversation_id}/restores`

```json
{"preview_id": "opaque-uuid"}
```

响应：

```json
{
  "operation_id": "uuid",
  "status": "completed",
  "restored_files": 3,
  "deleted_files": 1,
  "skipped_conflicts": [],
  "hidden_message_count": 8,
  "undo_available": true,
  "history_revision": 12
}
```

接口不变量：

- 复用 `ConversationService.get_owned`；越权按会话不存在处理。
- Preview 默认有效 10 分钟，并绑定 conversation revision、目标、模式和当前文件 hash。
- 执行时重新获取锁并重算 hash；不能只信任 preview。
- 活跃任务返回冲突，前端先取消后重试 preview。
- 手动/外部 hash 冲突计为 `partial`，不作为整单失败。
- 存储损坏、过期 target 和失效 preview fail-safe，不触碰文件或活动 head。

---

## 3. 执行逻辑

### 3.1 用户消息锚点

1. 接收用户消息后预生成 `user_message_id` 和 `checkpoint_id`。
2. 先原子写空 `CodeCheckpoint(status="open")`，再把带 `checkpoint_id` 的用户消息写入 JSONL。
3. 用户消息成为新的 `active_message_head_id`，并递增 `history_revision`。
4. 将 checkpoint ID 写入 LangGraph config metadata；输入 checkpoint 产生后立即回填 `graph_input_checkpoint_id`。
5. 工具执行前把 conversation、checkpoint、workspace root、tool call ID 放入 ContextVar，子 Agent 继承同一上下文。
6. 正常结束、取消或受控失败时封口；重启发现 `open` manifest 时改为 `interrupted`，不删除。

### 3.2 工具副作用分类和 mutation gateway

为 `ToolSpec` 增加：

```python
class ToolEffect(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_FILES = "workspace_files"
    EXTERNAL = "external"
    MEMORY = "memory"
```

- `write_file`、`edit_file`、工作区 skill 安装、GitHub 工作区产物声明为 `WORKSPACE_FILES`。
- `shell/bash`、MCP、未知自定义工具声明为 `EXTERNAL`。
- 记忆和知识库工具声明为 `MEMORY`。
- 只在 AI 工具上下文且 effect 为 `WORKSPACE_FILES` 时启用 checkpoint；WorkspaceService 的用户编辑不带该上下文。

统一 mutation API：

```python
class WorkspaceMutationGateway:
    async def write_bytes(self, relative_path: str, content: bytes, *, tool_call_id: str) -> None: ...
    async def delete_file(self, relative_path: str, *, tool_call_id: str) -> None: ...
    async def move_file(self, source: str, target: str, *, tool_call_id: str) -> None: ...
```

每个真实 mutation：

1. 规范化路径并验证仍位于 workspace root 内。
2. 获取规范化 workspace root/file 锁。
3. 读取原始 bytes；不存在则记录 `exists=False`。
4. 写入/复用 blob，并在 manifest 中持久化 `prepared` WAL。
5. 同轮同路径已有记录时不得替换其 `before`，只追加 tool call 并更新计划/最终 hash。
6. 在 mutation 前计算 `planned_after_sha256`，再执行临时文件加原子替换。
7. 成功后写 `final_after_sha256/status=applied`；失败写 `status=failed`。
8. Blob/manifest 写入失败时工具 fail-closed，文件不变。

写中崩溃恢复判定：

- 当前 hash 等于 `before`：mutation 未生效，无需恢复。
- 当前 hash 等于 `planned_after`：AI mutation 已生效，可安全恢复。
- 其他 hash：视为用户、外部进程或其他会话修改，默认跳过。

### 3.3 三种模式

- `code_only`：恢复目标锚点之后的受追踪文件变化；保留当前消息和 graph head。
- `conversation_only`：活动消息 head 截到选中用户消息，活动 graph head 切到该消息输入 checkpoint；文件不变。
- `both`：先恢复代码，再切换活动消息/graph head。

选中的用户消息自身保留，只隐藏其后的消息。新用户消息从当前活动 head 创建新分支；读取会话时沿 `history_parent_id` 返回当前分支，不返回隐藏未来。

若极端崩溃导致用户锚点缺少 graph input ID，则从父 graph head 加该用户消息重建分支；禁止回退到 JsonFileSaver 默认的最大 checkpoint ID。

### 3.4 恢复和撤销

1. Preview 只读计算目标状态、对话截断数量、当前 hash 和 diff。
2. 确认后获取 conversation 锁与规范化 workspace root 锁。
3. 再验证 preview、revision 和 hash。
4. 在修改任何文件前写 `RollbackOperation(status="prepared")`，把即将覆盖的当前文件存入 blob 并记录 `undo_files`。
5. 逐文件原子恢复；目标为不存在时仅在当前 hash 匹配 AI 产物时删除精确文件。
6. 只清理 mutation gateway 明确创建且当前为空的父目录，绝不递归删除非空目录。
7. 已知 hash 冲突跳过并继续；Both 模式仍执行对话截断，结果为 `partial`。
8. 操作系统 I/O 失败时停止后续文件，标记 `failed_partial`，保留原活动消息/graph head并提供重试或撤销。
9. 成功或仅有冲突时原子更新 cursor、active code node 和 revision。
10. 撤销操作先生成相同格式 preview；确认后以 `before_cursor/undo_files` 创建新的逆向 operation。旧 operation 永不修改或删除，因此可连续撤销、前进和再次撤销。

---

## 4. 前端交互

- `MessageBubble` 仅对 role=user 且 checkpoint 可用的消息提供“回滚到此状态”。
- 桌面端在 hover 或 `focus-within` 显示；键盘支持 Tab、Enter、Space；触屏端放入常显的 44px 消息操作菜单。
- `MessageBubble` emit `rollback(messageId, checkpointId)`，`MessageList` 上抛，由普通 `ChatView` 与工作区 `WorkspaceShell` 分别处理。
- 若当前 stream/task 活跃，先弹“停止当前任务并回滚？”；确认后调用现有 cancel，轮询到终态，刷新消息/文件状态，再请求 preview。取消失败不得执行恢复。
- 新建共享 `CheckpointRollbackDialog`，默认选择 `Code only`，展示：
  - 三种模式及影响说明；
  - 将隐藏的消息数量；
  - 文件恢复/删除动作；
  - 文本 diff 或二进制 hash/大小；
  - “已跳过：检测到手动或外部修改”；
  - 固定外部副作用限制提示；
  - 明确二次确认按钮。
- Code only 成功后刷新文件树、打开编辑器和 diff 状态，消息不变。
- Conversation only 成功后重新加载当前消息分支并清理旧 stream 状态，文件内容 UI 不刷新。
- Both 同时刷新消息、会话元数据、文件树和打开编辑器。
- 有冲突时显示“部分完成”，列出跳过文件；不得使用普通成功 toast 掩盖冲突。
- 成功 toast 提供“撤销本次回滚”。会话工具栏增加“回滚历史”入口，列出隐藏分支锚点和 operation，保证截断后仍能前后切换。
- 新接口必须同步 `src/api/chat.ts`、`src/types/api.ts` 和 `src/mock/server.ts`。

固定提示文案：

> 仅恢复 AI 通过受支持文件工具产生的文件改动。Shell/脚本、数据库、MCP/远程服务及手动编辑不会被快照或回滚；检测到手动或外部改动的文件将跳过。记忆和知识库不在本期范围。

---

## 5. 实施任务

## Task 1: 建立会话隔离 Blob/Manifest 存储

**Files:**

- Create: `app/checkpoints/models.py`
- Create: `app/checkpoints/store.py`
- Create: `app/checkpoints/service.py`
- Modify: `app/core/config.py`
- Modify: `app/core/bootstrap.py`
- Test: `tests/test_code_checkpoint_store.py`

**Interfaces:**

- Produces: `CodeCheckpointStore.create_checkpoint/read_checkpoint/prepare_file/finalize_file/seal_checkpoint`。
- Produces: `CheckpointService.create_anchor/bind_graph_checkpoint/mark_interrupted/cleanup_expired`。

- [ ] 写失败测试：空 checkpoint 原子创建、bytes blob 去重、二进制往返、会话隔离、manifest 损坏 fail-safe。
- [ ] 运行 `pytest tests/test_code_checkpoint_store.py -q`，确认新增测试失败。
- [ ] 实现模型、SHA-256 blob 布局、原子 JSON 写入和会话级锁。
- [ ] 实现 `checkpoint_retention_days=30`、启动时 open→interrupted 修复和小时级清理入口。
- [ ] 再次运行定点测试，确认通过。

## Task 2: 将用户消息、活动分支与 LangGraph head 绑定

**Files:**

- Modify: `app/storage/models/message.py`
- Modify: `app/storage/models/conversation.py`
- Modify: `app/storage/repositories/message.py`
- Modify: `app/orchestration/chat_stream.py`
- Modify: `app/orchestration/checkpointer.py`
- Test: `tests/test_message_checkpoint_anchor.py`
- Test: `tests/test_conversation_checkpoint_branch.py`

**Interfaces:**

- Consumes: Task 1 `CheckpointService.create_anchor`。
- Produces: `Message.checkpoint_id/history_parent_id`、Conversation cursor 字段、user-message↔graph-input checkpoint 映射。

- [ ] 写失败测试：消息前先有空 manifest、无文件修改仍有 checkpoint、受控错误和崩溃锚点可用。
- [ ] 写失败测试：按活动 head 回放消息、截断后创建新分支、隐藏未来不进入下一次 LangGraph 上下文。
- [ ] 运行两组定点测试并确认失败。
- [ ] 让 MessageRepository 接受预生成 message ID，并在消息 append 后维护活动 head。
- [ ] 给 graph config metadata 注入 user message/checkpoint ID；扩展 JsonFileSaver 查询和显式 active head 解析。
- [ ] 实现旧会话缺少 history_parent_id 时按既有排序惰性建立基线链，但不生成代码快照。
- [ ] 再次运行定点测试，确认通过。

## Task 3: 统一 AI 工作区文件 Mutation Gateway

**Files:**

- Modify: `app/tools/registry.py`
- Modify: `app/tools/context.py`
- Modify: `app/tools/filesystem.py`
- Modify: `app/orchestration/nodes/tool_execute.py`
- Modify: `app/tools/builtin/file_ops.py`
- Modify: `app/tools/builtin/install_skill.py`
- Modify: `app/services/github_hotspot.py`
- Test: `tests/test_checkpoint_mutation_gateway.py`

**Interfaces:**

- Consumes: Task 1 `CodeCheckpointStore.prepare_file/finalize_file`。
- Produces: `ToolEffect`、checkpoint ContextVar、`WorkspaceMutationGateway.write_bytes/delete_file/move_file`。

- [ ] 写失败测试：write/edit 首次前镜像、同轮重复修改、创建文件 tombstone、二进制写回、snapshot 失败 fail-closed。
- [ ] 写失败测试：WorkspaceService 手动编辑、shell、MCP、记忆不生成记录；workspace skill 和 GitHub 多文件产物生成记录。
- [ ] 写崩溃测试：WAL 后未写、原子写后未 finalize、工具异常后的 checkpoint 均可判定。
- [ ] 运行 `pytest tests/test_checkpoint_mutation_gateway.py -q`，确认失败。
- [ ] 实现 ToolEffect、ContextVar 和 gateway，将所有纳入范围的直接文件写入迁移到 gateway。
- [ ] 停止 write/edit 生成新的 `.agent/.undo` 备份；从 Agent 默认工具集中弃用旧 `tl_undo_file`，保留旧备份文件不主动删除。
- [ ] 再次运行定点测试，确认通过。

## Task 4: 实现 Preview、三模式恢复和可逆 Operation

**Files:**

- Create: `app/checkpoints/restore.py`
- Modify: `app/checkpoints/service.py`
- Modify: `app/storage/repositories/message.py`
- Modify: `app/services/conversation.py`
- Test: `tests/test_checkpoint_restore.py`
- Test: `tests/test_checkpoint_restore_concurrency.py`

**Interfaces:**

- Produces: `CheckpointService.preview_restore(...) -> RestorePreview`。
- Produces: `CheckpointService.execute_restore(preview_id) -> RollbackOperation`。
- Produces: operation-before target，用于撤销任意 rollback。

- [ ] 写失败测试：文本 diff、二进制摘要、新建文件删除、Code/Conversation/Both 三模式。
- [ ] 写失败测试：preview 后手动修改被跳过、其他文件继续、结果为 partial。
- [ ] 写失败测试：rollback 自身撤销、撤销后再次前进、多轮历史切换。
- [ ] 写并发测试：同 workspace 多会话写入、活跃任务、过期 preview、revision 改变和文件 I/O 中断。
- [ ] 运行定点测试并确认失败。
- [ ] 实现目标状态遍历、workspace/conversation 锁、短期 preview store、rollback WAL 和逐文件原子恢复。
- [ ] 实现活动 message/graph/code cursor 切换以及 failed_partial 不移动对话 head 的语义。
- [ ] 再次运行定点测试，确认通过。

## Task 5: 暴露 API 并整合清理生命周期

**Files:**

- Modify: `app/api/schemas/conversations.py`
- Modify: `app/api/routers/conversations.py`
- Modify: `app/services/serializers.py`
- Modify: `app/api/main.py`
- Modify: `app/core/session_cache.py`
- Modify: `app/services/workspace.py`
- Test: `tests/test_checkpoint_api.py`
- Test: `tests/test_checkpoint_cleanup.py`

**Interfaces:**

- Produces: `GET /conversations/{id}/checkpoints`。
- Produces: `POST /conversations/{id}/restore-previews`。
- Produces: `POST /conversations/{id}/restores`。
- Extends: message serialization 的 `checkpoint` 摘要。

- [ ] 写 API 失败测试：owner 隔离、三类接口 schema、活跃任务冲突、过期/损坏 checkpoint、partial 响应。
- [ ] 写清理失败测试：30 天非活跃会话删除 checkpoint；有效 checkpoint 阻止普通会话工作区被 7 天清理提前删除；会话/工作区删除时清理 checkpoint 数据。
- [ ] 运行定点测试并确认失败。
- [ ] 实现 schema/router/serializer 和 lifespan cleanup task。
- [ ] 增加按 conversation 查询活跃 Task 的服务方法；restore API 始终拒绝运行中任务。
- [ ] 再次运行定点测试，确认通过。

## Task 6: 前端消息入口、预览弹窗与历史切换

**Files:**

- Create: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/business/CheckpointRollbackDialog.vue`
- Create: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/business/CheckpointHistoryDialog.vue`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/business/MessageBubble.vue`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/business/MessageList.vue`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/views/ChatView.vue`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/components/workspace/WorkspaceShell.vue`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/api/chat.ts`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/types/api.ts`
- Modify: `C:/Users/Admin1/Desktop/Agent/FrontEnd/src/mock/server.ts`

**Interfaces:**

- Consumes: Task 5 REST API。
- Produces: `rollback(messageId, checkpointId)` 消息事件、共享 rollback/history dialogs。

- [ ] 添加 MessageBubble/MessageList Vitest：hover、focus-within、键盘和触屏入口，只在用户 checkpoint 可用时显示。
- [ ] 添加 dialog Vitest：三模式、默认 Code only、文本/二进制预览、冲突、限制提示、确认禁用和 partial 结果。
- [ ] 添加 ChatView/WorkspaceShell 测试：运行中先取消、等待终态、重新 preview，以及各模式的正确刷新范围。
- [ ] 添加 API 与 mock server 契约测试、operation 撤销与隐藏历史切换测试。
- [ ] 运行相关 Vitest，确认新增测试失败。
- [ ] 实现组件、类型、API、mock 及普通/工作区两条状态链。
- [ ] 运行 `npm run typecheck`、`npm run lint:check` 和 `npm run test:unit`，确认通过。
- [ ] 运行 Playwright 的 `/chat` 与工作区聊天交互测试，覆盖 390×844、800×900、1440×900。

## Task 7: 回归、构建同步与交付 Gate

**Files:**

- Update: `docs/03-api-contracts.md`
- Update: `README.md`
- Generate from frontend build: `frontend_dist/index.html`, `frontend_dist/assets/*`

- [ ] 运行 checkpoint 定点后端测试。
- [ ] 运行完整 `pytest -q`，确认无回归。
- [ ] 在前端仓库运行 `npm run typecheck`、`npm run lint:check`、`npm run test:unit`、`npm run build`。
- [ ] 使用现有同步流程把前端 `dist` 同步到后端 `frontend_dist`，不手改压缩 bundle。
- [ ] 使用真实后端验证：空 checkpoint、文本/二进制恢复、三模式、手动冲突跳过、运行中取消、rollback 撤销。
- [ ] 按仓库约定使用 `review-test-simplify` 完成 Test/Review/Simplify 三道 gate，修复 P0/P1/P2 问题后再提交。

---

## 6. 验收标准

- [ ] 每条新用户消息都有独立 checkpoint，且 AI/工具崩溃后仍可使用。
- [ ] 同轮同文件只保存一次初始原文；blob 可复用且二进制无损。
- [ ] 用户手动编辑和其他会话改动不会被回滚覆盖。
- [ ] Shell、脚本、数据库、MCP/远程服务副作用从不声称可恢复，UI 始终提示限制。
- [ ] Code only、Conversation only、Both 的文件/消息/graph 行为与定义一致。
- [ ] 所有恢复先展示 preview，再由用户确认执行。
- [ ] 对话截断后可以从历史入口回到隐藏节点；rollback 操作可以再次撤销。
- [ ] 记忆、知识库和长会话分页未被引入本期实现。
