# Checkpoint 回滚正确性修复 — 后端实施计划

**状态：** `COMPLETED`。用户已明确批准按本计划执行；实现按 Task 顺序完成并记录于 `progress-checkpoint-rollback-correctness.md`。

**Goal：** 修复消息级 checkpoint 的图上下文、目标消息撤回、模式游标、preview 一致性和恢复 WAL，使三种模式满足冻结契约，并保证回滚目标用户消息后其正文、附件、文件引用返回草稿且不再出现在 active 消息/轨迹/下一轮模型上下文中。

**Architecture：** 文件 checkpoint、消息 branch cursor、LangGraph cursor 三者保持独立。每轮 code checkpoint 绑定真实的 graph parent/output；conversation modes 将消息和 graph cursor 移到目标用户输入之前，code mode 只移动文件 cursor。恢复执行采用 durable operation journal：写文件前持久化 preview 计划、undo blobs 与 before/after cursors，逐文件更新状态，异常后仍能执行 operation-before 回滚。

**Execution skill：** 批准后使用 `executor-debugger`，按 Task 顺序执行并维护 `progress-checkpoint-rollback-correctness.md`。提交前必须使用 `review-test-simplify`。

---

## 冻结契约：`checkpoint-restore-v2`

### 三模式游标矩阵

| 模式 | message cursor | graph cursor | code cursor | 草稿 |
|---|---|---|---|---|
| `code_only` | 不变 | 不变 | 完整成功为 `target.id`；混合状态见下方规则 | `null` |
| `conversation_only` | `target.anchor_message_head_id` | 目标输入前 graph parent | 不变 | 目标用户消息 |
| `both` | `target.anchor_message_head_id` | 目标输入前 graph parent | 完整成功为 `target.id`；混合状态见下方规则 | 目标用户消息 |

- 所有成功执行（包括 code-only 和 operation undo）都令 `history_revision += 1`，使旧 preview 失效。
- conversation modes 的 `hidden_message_count` 包含目标用户消息本身。
- Both 中部分文件冲突不会阻止消息/graph 撤回；返回 `partial` 并列出跳过路径。
- 文件阶段完整成功时 code cursor=`target.id`；正常完成为 partial 且至少应用一个路径时 code cursor=`operation.id`，表示可再次回滚的合成工作区状态；零路径应用时保留 before code cursor。`failed_partial` 返回实际已提交的 cursor：若混合状态 cursor 已提交则为 operation id，若 cursor commit 本身失败则暂为 before，journal 单独记录混合文件状态并阻止后续 restore，直到恢复流程修复/撤销。不得把混合工作区标成完整 target。
- 草稿包含 `content + attachments + file_refs`；附件只复用引用，不复制、不删除、不改变 blob。
- `failed_partial` 响应必须返回真实已提交的 conversation action：cursor 已提交则为 `withdraw_from_target`/`restore_cursor`，未提交则为 `unchanged`。前端不得依据 status 猜测。
- shell、脚本、数据库、MCP、远程服务、记忆和知识库仍不纳入恢复。

### 请求与响应

修改 `app/api/schemas/checkpoints.py`：

```python
class CheckpointRestorePreviewRequest(BaseModel):
    target_type: Literal['checkpoint']
    target_checkpoint_id: UUID
    mode: Literal['code_only', 'conversation_only', 'both']
    client_request_id: str

class OperationBeforeRestorePreviewRequest(BaseModel):
    target_type: Literal['rollback_operation_before']
    target_id: UUID
    client_request_id: str

RestorePreviewRequest = Annotated[
    CheckpointRestorePreviewRequest | OperationBeforeRestorePreviewRequest,
    Field(discriminator='target_type'),
]

class RestoreExecuteRequest(BaseModel):
    preview_id: UUID
    expected_mode: Literal['code_only', 'conversation_only', 'both'] | null
    client_request_id: str | null
```

Preview 与 execute 统一返回以下 conversation 结构：

```json
{
  "action": "unchanged | withdraw_from_target | restore_cursor",
  "active_message_head_after_id": "uuid-or-null",
  "withdrawn_from_message_id": "uuid-or-null",
  "hidden_message_count": 0,
  "draft": {
    "source_message_id": "uuid",
    "content": "原用户输入",
    "attachments": [
      {
        "attachment_id": "uuid",
        "name": "原文件名",
        "mime_type": "application/octet-stream",
        "size": 123,
        "status": "ready",
        "available": true,
        "unavailable_reason": null
      }
    ],
    "file_refs": []
  }
}
```

顶层必须回显：

```json
{
  "preview_id": "uuid",
  "client_request_id": "uuid",
  "mode": "both",
  "target": {"type": "checkpoint", "id": "uuid", "message_id": "uuid"},
  "conversation_revision": 12
}
```

Execute 额外返回 `operation_id`、`target_message_id`、文件统计、`undo_available` 和新 `history_revision`。后端在 restore lock 内验证 `expected_mode == preview.mode`、request id、conversation owner、target、revision、active code cursor、workspace identity、TTL 和 preview 文件 hashes。

兼容策略：`client_request_id` 作为不透明字符串（UUID 仍可用）；preview 缺省时由服务端生成。首版静态 bundle 还省略了 preview 的 `target_type`，服务端仅在存在 `target_checkpoint_id` 且类型字段缺失时推断为 `checkpoint`，其他未知/不完整 payload 仍由 discriminated union 拒绝。`expected_mode` 与 execute 的 request id 在旧静态 bundle 缺失时允许为空，但只要 v2 客户端提交，服务端仍严格执行 mode/request-id 绑定校验。

---

## 数据结构决定

### Conversation 与 ConversationCursor

修改 `app/storage/models/conversation.py` 和 `app/checkpoints/models.py`：

```python
message_cursor_initialized: bool = False
active_message_head_id: UUID | None = None

graph_cursor_initialized: bool = False
active_graph_checkpoint_id: str | None = None

active_code_node_id: UUID | None = None
history_revision: int = 0
```

- `message_cursor_initialized=True, head=None` 表示主动回滚到空对话；只有 `False, head=None` 才允许旧 append-only fallback。
- `graph_cursor_initialized=True, checkpoint=None` 表示显式从空图开始；checkpointer 不得退回线程最新状态。
- `ConversationCursor` 同步持久化两个 initialized 标志，确保 operation undo 能恢复空分支语义。

### CodeCheckpoint manifest v2

```python
graph_parent_checkpoint_id: str | None
graph_parent_bound: bool = False
graph_output_checkpoint_id: str | None = None
```

- parent 是目标用户输入进入 graph 前的真实 LangGraph checkpoint。
- `bound=True/id=None` 是合法图根，与旧 manifest 未绑定严格区分。
- output 是本轮完成、中断或错误后的真实 graph checkpoint。
- v2 reader 兼容旧 `graph_input_checkpoint_id`，但不得把缺失字段解释为合法图根。

### RollbackOperation WAL

扩展 `RollbackOperation`：

```python
preview_id: UUID
target_user_message_id: UUID
planned_files: list[FileRestorePlan]
applied_paths: list[str]
before_cursor: ConversationCursor
planned_after_cursor: ConversationCursor
after_cursor: ConversationCursor | None
undo_files: dict[str, FileVersionRef]
status: Literal['prepared', 'applying', 'completed', 'partial', 'failed_partial']
error: dict[str, Any] | None
updated_at: datetime
```

`FileRestorePlan` 必须持久化 path、action、content kind、preview current hash、target ref 和 conflict 状态。旧 operation reader 继续接受 `after_cursor=None`，并为 `preview_id/planned_files/applied_paths/error/updated_at` 提供兼容默认值；新 operation writer 使用 schema v2。`CodeCheckpointStore` 增加原子 `update_operation()`；不能继续只在恢复末尾 create-once。

Prepared 阶段持久化 `planned_after_cursor`；只有 cursor commit 成功后才写实际 `after_cursor`。Operation undo 应用 stored before/after cursor 时只恢复 message/graph/code cursor 及 initialized flags；stored `history_revision` 只用于审计，绝不把当前 revision 倒退。每次执行的结果 revision 固定为“执行前当前 revision + 1”。若 operation-before 恢复旧消息 branch，conversation action=`restore_cursor`、draft=null。

---

## Task 1：修正消息 branch 的“空 head”表达

**Files：**

- Modify: `app/storage/models/conversation.py:20-25`
- Modify: `app/storage/repositories/message.py:23-64`
- Modify: `app/services/conversation.py:61-109`
- Modify: `app/orchestration/chat_stream.py:268-285`
- Modify: `app/checkpoints/restore.py:177-214`
- Modify: `app/checkpoints/models.py:197-224`
- Test: `tests/test_checkpoint_restore.py`
- Create: `tests/test_conversation_service.py`

**Interfaces：**

- Produces: `message_cursor_initialized` 与 `ConversationCursor.message_cursor_initialized`。
- `MessageRepository.list_active/count_active` 新增关键字参数 `cursor_initialized: bool`；只有其为 false 且 head 为 null 时使用 legacy fallback。

- [ ] Step 1: 写失败测试 `test_initialized_null_head_returns_empty_active_messages_and_trajectory`。
- [ ] Step 2: 写失败测试 `test_legacy_null_head_still_returns_append_only_history`。
- [ ] Step 3: 写失败测试 `test_conversation_cursor_round_trip_preserves_initialized_empty_head`。
- [ ] Step 4: 运行定向测试，预期失败。
- [ ] Step 5: 增加字段并修改消息、trajectory、preview 的所有 active-list 调用方；新用户消息落库时设置 `message_cursor_initialized=True`。
- [ ] Step 6: 重跑测试和 `ruff check`，预期通过。
- [ ] Step 7: 提交 `fix(checkpoint): distinguish empty branch from legacy history`。

## Task 2：记录并消费真实 LangGraph parent/output cursor

**Files：**

- Modify: `app/checkpoints/models.py:99-157`
- Modify: `app/checkpoints/store.py:313-320`
- Modify: `app/checkpoints/service.py`
- Modify: `app/orchestration/checkpointer.py:126-290`
- Modify: `app/orchestration/chat_stream.py:85-112,199-224,314-322,392-395,650-660,727-729`
- Modify: `app/checkpoints/restore.py:177-260`
- Modify: `app/api/routers/checkpoints.py:80-124`
- Modify: interrupt/error sealing paths in `app/orchestration/chat_stream.py`
- Test: `tests/test_code_checkpoint_store.py`
- Test: `tests/test_chat_stream.py`
- Test: `tests/test_interrupt_stream.py`

**Interfaces：**

- `JsonFileSaver.put()` 的 record 索引额外保存 `code_checkpoint_id`、`metadata.source`、`parent_checkpoint_id`。
- 新增：

```python
async def aget_run_bounds(config: dict[str, Any], code_checkpoint_id: str) -> tuple[str | None, str | None]
```

- `_graph_config()` 明确接收 `code_checkpoint_id`、`parent_graph_checkpoint_id`、`start_graph_from_root`；parent 写入 `configurable.checkpoint_id`，显式图根写入 `start_graph_from_root=True`。
- `JsonFileSaver.get_tuple()` 的优先级固定为：存在且有效的显式 `checkpoint_id` 时读取该节点（包括 transport retry）；否则 `start_graph_from_root=True` 才返回 `None`；最后才允许 legacy latest fallback。root 标志不得覆盖 `aget_failed_config()` 产生的显式失败重试 checkpoint。
- `CheckpointRestoreService` 构造函数接收 `graph_checkpoint_resolver`；router 增加 `Request` 并从 `request.app.state.checkpointer` 注入，测试注入 fake resolver。preview 的懒绑定不使用隐式全局 app state。

- [ ] Step 1: 写失败测试：saver 能按 `code_checkpoint_id` 解析本轮 input parent 和 output；首轮返回 `(None, output)`。
- [ ] Step 2: 写失败测试：无显式 checkpoint 时 `start_graph_from_root=True` 返回 None；同时写 transport retry 测试，带有效显式 failed checkpoint 时即使保留 root flag 也必须读取该节点。
- [ ] Step 3: 写失败测试：第二轮 `_graph_config` 使用第一轮真实 output id，而不是 code checkpoint UUID。
- [ ] Step 4: 写失败测试：完成、interrupt、error 三条路径都绑定 manifest 的 graph parent/output。
- [ ] Step 5: 运行定向测试，预期失败。
- [ ] Step 6: 实现 v2 manifest reader/writer 和 saver run-bounds 索引；router 将 app saver resolver 注入 restore service，进程在 seal 前崩溃时 preview 可按 code id 懒解析并补绑定。
- [ ] Step 7: 删除两处 `active_graph_checkpoint_id = str(code_checkpoint_id)`；改写为 actual graph output，并设置 `graph_cursor_initialized=True`。
- [ ] Step 8: 新一轮 graph config 消费 conversation 当前 graph cursor；显式空图不得加载旧最新状态。
- [ ] Step 9: 重跑测试、Ruff 和 compileall，预期通过。
- [ ] Step 10: 提交 `fix(checkpoint): bind real langgraph cursors to message anchors`。

## Task 3：实现目标用户消息撤回和权威草稿响应

**Files：**

- Modify: `app/storage/repositories/message.py`
- Modify: `app/checkpoints/restore.py:177-337`
- Modify: `app/api/routers/checkpoints.py:80-124`
- Modify: `app/services/serializers.py`
- Modify: `app/storage/repositories/attachment.py`
- Test: `tests/test_checkpoint_restore.py`
- Test: `tests/test_checkpoint_api.py`

**Interfaces：**

- 新增 `MessageRepository.get_in_conversation(conversation_id, message_id)`。
- Preview 必须验证目标消息属于当前 conversation、role=user、`message.checkpoint_id == target.id`，且 `history_parent_id == target.anchor_message_head_id`。只有 `conversation_only/both` 要求目标位于当前 active message branch；`code_only` 允许切换 detached/future checkpoint，以保留多次代码节点来回切换。
- Produces: 冻结契约中的 `RestoreConversationPlan`。
- Draft attachment 以消息内历史快照保留 name/mime/size/order，再用 `AttachmentRepository.get(conversation.user_id, attachment_id)` 查询当前状态；row 不存在或 status=`failed` 时返回 `available=false` 和原因，其余状态可复用。不得删除或重新绑定附件。

- [ ] Step 1: 构造 `U1/A1/U2/A2`，写失败测试 `test_conversation_modes_withdraw_target_to_anchor_and_return_full_draft`：回滚 U2 后 head=A1，U2/A2 隐藏，draft=U2。
- [ ] Step 2: 写失败测试 `test_withdraw_first_user_message_leaves_empty_active_history_and_trajectory`。
- [ ] Step 3: 写失败测试：draft 保留附件顺序、历史元数据和 `file_refs`；当前 row 缺失/failed 返回 `available=false/unavailable_reason`，可用 row 返回当前 status。
- [ ] Step 4: 写失败测试：`conversation_only` 保持文件和 code cursor 不变；`both` 移动三类 cursor；`code_only` 只移动 code cursor且 draft=null。
- [ ] Step 5: 写失败测试：Both 文件部分冲突时仍撤回 conversation 并返回 draft。
- [ ] Step 6: 运行定向测试，预期失败。
- [ ] Step 7: 将 conversation modes 的 message head 设为 `target.anchor_message_head_id`，graph cursor 设为 graph parent；code-only 不动它们。
- [ ] Step 8: 将隐藏数改为 `len(active_messages) - target_position`，包含目标消息。
- [ ] Step 9: execute 成功响应返回与 preview 同形的权威 conversation plan；附件只返回引用，不修改归属或 blob。
- [ ] Step 10: 重跑测试和 Ruff，预期通过。
- [ ] Step 11: 提交 `feat(checkpoint): withdraw restored user turn into draft`。

## Task 4：绑定 Preview 的模式、目标和精确文件计划

**Files：**

- Modify: `app/api/schemas/checkpoints.py`
- Modify: `app/api/routers/checkpoints.py`
- Modify: `app/checkpoints/restore.py:39-337`
- Test: `tests/test_checkpoint_api.py`
- Test: `tests/test_checkpoint_restore.py`

**Interfaces：**

- Consumes: `client_request_id` 和 `expected_mode`。
- Preview record 绑定 conversation id、history revision、active code node、target、mode、workspace identity、文件 planned refs、preview current hashes 和 expires_at。
- 每个 conversation 使用 restore lock；execute 在锁内 claim preview，并按 `operation_id` 幂等。

- [ ] Step 1: 写失败测试：mode 与 preview 不一致返回 40936，且无 cursor/文件副作用。
- [ ] Step 2: 写失败测试：乱序 preview 分别回显自己的 request id/mode；execute request id 不一致被拒绝。
- [ ] Step 3: 写失败测试：code-only restore 后旧 preview 因 active code node/revision 改变而失效。
- [ ] Step 4: 写失败测试：execute 只验证并执行 preview 中的 paths/refs，不重新生成另一份 `_file_plan`；预览后 hash 改变只产生 conflict/拒绝，不扩展计划。
- [ ] Step 4a: 写失败测试：部分文件恢复后 code cursor 为 operation id；全部冲突零应用时保留 before code cursor；不得指向完整 target。
- [ ] Step 5: 写并发测试：同一 preview 并发 execute 只创建一个 operation，重复调用幂等返回相同结果。
- [ ] Step 6: 运行定向测试，预期失败。
- [ ] Step 7: 扩展 schema、record 和 lock；所有成功 restore 均递增 revision。
- [ ] Step 8: 重跑测试和 Ruff，预期通过。
- [ ] Step 9: 提交 `fix(checkpoint): bind restore execution to confirmed preview`。

## Task 5：将文件恢复和逆恢复改成 Durable WAL

**Files：**

- Modify: `app/checkpoints/models.py:225-307`
- Modify: `app/checkpoints/store.py:133-169`
- Modify: `app/checkpoints/restore.py:239-470`
- Modify: `app/checkpoints/service.py`
- Modify: `app/api/main.py:47-77`
- Test: `tests/test_code_checkpoint_store.py`
- Test: `tests/test_checkpoint_restore.py`
- Test: `tests/test_checkpoint_api.py`

**Interfaces：**

- Produces: `update_operation()` 和 `recover_incomplete_operations()`。
- 正向 checkpoint restore 与 `rollback_operation_before` 必须共用同一 journal executor。

- [ ] Step 1: 写失败测试：所有目标 blob 在第一次文件写前完成 preflight；第二个 blob 缺失时零文件被改。
- [ ] Step 2: 写失败测试：operation 的 `prepared` 记录和全部 undo blobs 在第一次 replace/unlink 前已经 durable。
- [ ] Step 3: 故障注入：首文件后、cursor commit 时、final operation update 时抛错；每种情况均存在可读 operation、`applied_paths` 和 undo refs，状态为 `failed_partial`。cursor commit 失败时 `after_cursor=None`、conversation 保持 before cursor，且 incomplete-operation guard 阻止新 restore。
- [ ] Step 4: 写失败测试：operation-before 能撤销上述 partial operation，并恢复 before cursor。
- [ ] Step 4a: 写失败测试：operation-before 恢复 message branch 时返回 `action='restore_cursor'`；revision 为执行前当前值 + 1，不恢复 stored 旧 revision。
- [ ] Step 5: 写失败测试：启动扫描 prepared/applying operation，不自动覆盖工作区；能证明完整的标记完成，其余标记 failed_partial 并保留诊断信息。
- [ ] Step 6: 运行定向测试，预期失败。
- [ ] Step 7: 实现执行顺序：restore lock → claim preview → preflight target blobs → capture undo blobs → create prepared（含 planned_after_cursor，actual after_cursor=null）→ applying → 每路径原子写并 update → 计算并 commit actual cursor → 写 after_cursor → completed/partial。
- [ ] Step 8: 任一 prepared 后异常持久化 `failed_partial/error`；不得删除 preview/operation 证据。
- [ ] Step 9: 将逆恢复迁移到同一 executor，消除当前先改文件再创建 inverse operation 的路径。
- [ ] Step 10: 在 lifespan 中调用 incomplete-operation recovery；不自动覆盖无法证明状态的文件。
- [ ] Step 11: 重跑定向测试、Ruff、compileall，预期通过。
- [ ] Step 12: 提交 `fix(checkpoint): journal restore operations before file mutation`。

## Task 6：准确表达写入、删除和 finalize 后状态

**Files：**

- Modify: `app/checkpoints/models.py:59-95`
- Modify: `app/checkpoints/store.py:225-310`
- Modify: `app/checkpoints/mutation.py:55-145`
- Modify: `app/checkpoints/restore.py:112-139`
- Test: `tests/test_code_checkpoint_store.py`
- Create: `tests/test_checkpoint_mutation.py`

**Interfaces：**

- `FileMutationRecord` 不再用 nullable hash 同时表示“文件不存在”和“尚未记录”。采用显式状态：

```python
@dataclass(frozen=True)
class FileAfterState:
    exists: bool
    sha256: str | None
    size_bytes: int | None = None
    content_kind: ContentKind | None = None

planned_after: FileAfterState
final_after: FileAfterState | None
final_after_recorded: bool = False
```

`FileAfterState` 只描述观测状态，不承诺对应 blob 可读取；before/undo 继续使用 `FileVersionRef`。v1 映射必须结合 mutation status，不能只看 nullable hash：`planned_after_sha256 is None` 映射 planned `exists=false`；`status='prepared'` 映射 `final_after_recorded=false`；`status in {'applied','failed'}` 映射 `final_after_recorded=true`，此时 final hash 为 null 明确表示 final `exists=false`。不得制造不存在的 blob 引用。

- [ ] Step 1: 写失败测试 `test_write_then_delete_in_same_checkpoint_records_final_nonexistence`。
- [ ] Step 2: 写失败测试 `test_new_file_then_delete_is_not_false_restore_conflict`。
- [ ] Step 3: 写失败测试 `test_delete_then_recreate_records_latest_final_bytes`。
- [ ] Step 4: 写失败测试：replace 成功、finalize 前崩溃仍能用 planned ref 安全恢复。
- [ ] Step 4a: 写 v1 迁移测试：prepared+final null 与 applied/failed+final null 分别映射“未 finalize”和“已 finalize 删除”。
- [ ] Step 5: 运行定向测试，预期失败。
- [ ] Step 6: 实现 FileAfterState 和 v1 兼容读取；restore expected state 优先 final recorded，否则 planned，不再使用 `final_hash or planned_hash`，也不尝试从 after state 读取 blob。
- [ ] Step 7: 重跑定向测试和 Ruff，预期通过。
- [ ] Step 8: 提交 `fix(checkpoint): represent deleted mutation outcomes explicitly`。

## Task 7：旧会话与 v1 Manifest 的安全兼容

**Files：**

- Modify: `app/checkpoints/models.py`
- Modify: `app/checkpoints/restore.py`
- Modify: `app/services/conversation.py`
- Modify: `app/orchestration/checkpointer.py`
- Test: `tests/test_checkpoint_identity.py`
- Test: `tests/test_code_checkpoint_store.py`
- Test: `tests/test_checkpoint_api.py`

**Interfaces：**

- 旧 conversation：head 非空可懒初始化 message cursor；旧 graph id 必须先验证为 saver 中真实 ID，不能消费当前错误写入的 code checkpoint UUID。
- v1 manifest：`anchor_message_head_id` 可用于消息草稿与截断；旧 `graph_input_checkpoint_id` 仅是旧 input checkpoint 候选。必须先验证它对应真实 LangGraph `metadata.source='input'` record，再读取该 record 的 `parent_checkpoint_id` 作为 v2 graph parent；绝不能把旧 input id 本身直接当 parent。
- 无法解析 graph parent 的旧 checkpoint：`code_only` 仍可用；`conversation_only/both` preview 返回 40937，并在消息 checkpoint summary 中设置 `can_restore_conversation=false`，不得假装从最新 graph 继续。

- [ ] Step 1: 写 v1/v2 round-trip 测试，区分 `bound=True/id=None` 与 unbound。
- [ ] Step 1a: 写旧 `graph_input_checkpoint_id` 迁移测试：验证 input record 后取其 parent；非法/不存在/source 非 input 均保持 unbound。
- [ ] Step 2: 写旧 conversation 测试：active head 对应 append-only 最后一条时，可将 graph cursor修复为 saver 当前真实 latest。
- [ ] Step 3: 写测试：错误 code checkpoint UUID 不会被当成 LangGraph id。
- [ ] Step 4: 写测试：无法验证 graph parent 的旧 checkpoint 禁用 conversation modes，但 code-only 可预览执行。
- [ ] Step 4a: 写旧 RollbackOperation v1 reader 测试：`after_cursor=None` 和新增字段缺失仍可读取、审计和安全 preview。
- [ ] Step 5: 运行定向测试，预期失败。
- [ ] Step 6: 实现懒迁移和错误码/summary 能力位；不得批量猜测不可证明的历史分支。
- [ ] Step 7: 重跑定向测试和 Ruff，预期通过。
- [ ] Step 8: 提交 `fix(checkpoint): safely gate legacy conversation restores`。

## Task 8：端到端回归与交付 Gate

**Files：**

- Modify: `tests/test_checkpoint_restore.py`
- Modify: `tests/test_checkpoint_api.py`
- Modify: `tests/test_chat_stream.py`
- Modify: `tests/test_interrupt_stream.py`
- Modify: `tests/test_code_checkpoint_store.py`
- Modify: `progress-checkpoint-rollback-correctness.md`

**Interfaces：**

- Consumes: Tasks 1–7 和前端已审批的 v2 契约。
- Produces: 可交给前端真实联调的稳定后端。

- [ ] Step 1: E2E 风格测试 `U1/A1/U2/A2 → rollback U2 → resend U2'`，断言消息与 trajectory 不含 U2/A2，graph parent 为 U1/A1，模型输入不含撤回分支。
- [ ] Step 2: 回滚 U1，断言 active 消息/轨迹为空且下一轮 `start_graph_from_root` 不加载旧 thread latest。
- [ ] Step 3: 覆盖三模式、附件/file_refs、二进制、空 checkpoint、手动文件冲突、部分恢复、operation undo、运行中阻断和跨会话 owner。
- [ ] Step 4: 覆盖 AI 崩溃/工具错误后已生成 checkpoint 仍可 preview；覆盖 restore 自身各故障点的 durable operation。
- [ ] Step 5: 运行 checkpoint/chat/interrupt 定向测试。
- [ ] Step 6: 运行全量 `pytest -q`、`ruff check app tests`、`python -m compileall -q app`、`git diff --check`。
- [ ] Step 7: 使用 `review-test-simplify` 执行 Test/Review/Simplify；任何 Critical/High/Medium finding 必须修复或由用户明确接受。
- [ ] Step 8: 更新 progress ledger，列出每个 commit、测试命令与结果。
- [ ] Step 9: 提交 `test(checkpoint): verify withdrawn-turn rollback invariants`。

---

## 明确不纳入本计划

- 记忆、知识库和数据库状态回滚。
- shell、脚本、MCP、远程服务副作用回滚。
- 长会话 checkpoint 列表分页与 blob 压缩优化。
- 对无法证明 graph parent 的旧 checkpoint 猜测或静默降级。

## 用户审批清单

- [ ] 同意 conversation modes 删除目标用户消息本身，并把文本、附件、`file_refs` 返回草稿。
- [ ] 同意 Both 部分文件冲突时仍撤回 conversation。
- [ ] 同意为旧且无法验证 graph parent 的 checkpoint 禁用 conversation rollback，而不是伪成功。
- [ ] 同意引入 initialized cursor、manifest v2、preview request id 和 durable operation WAL。
- [ ] 同意按 Tasks 1–8 使用 `executor-debugger` 执行，并在最终提交前运行完整 gate。

## 审批记录

`APPROVED — 用户已于 2026-08-30 明确要求“前端已经开始做了，你也开始执行吧”。`
