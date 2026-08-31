"""FileStore 设施测试：FileTable 原子写/JSONL append/并发安全/回滚重载。"""
from __future__ import annotations

import asyncio
import json
import uuid

from app.storage.file.store import FileContext, get_store
from app.storage.models.task import Task


async def test_filetable_register_and_flush():
    store = get_store()
    table = store.table("tasks")
    task = Task(user_id=uuid.UUID(int=0), agent_id=uuid.UUID(int=0), status="pending")
    table.register(task)
    await FileContext(store).commit()
    # 新 store 实例读回（模拟重启）
    got = await table.get(task.id)
    assert got is not None and got.status == "pending"
    assert got.id == task.id


async def test_row_dirty_tracking_persists_field_change():
    store = get_store()
    table = store.table("tasks")
    task = Task(user_id=uuid.UUID(int=0), agent_id=uuid.UUID(int=0), status="pending")
    table.register(task)
    await FileContext(store).commit()
    task.status = "running"  # 服务层直接赋值 → 标脏
    await FileContext(store).commit()
    got = await table.get(task.id)
    assert got.status == "running"


async def test_jsonl_append_and_list():
    store = get_store()
    await store.jsonl_append("sessions/test.jsonl", {"id": "a", "n": 1})
    await store.jsonl_append("sessions/test.jsonl", {"id": "b", "n": 2})
    records = await store.jsonl_list("sessions/test.jsonl")
    assert [r["id"] for r in records] == ["a", "b"]


async def test_rollback_reloads_from_disk():
    store = get_store()
    table = store.table("tasks")
    task = Task(user_id=uuid.UUID(int=0), agent_id=uuid.UUID(int=0), status="pending")
    table.register(task)
    await FileContext(store).commit()
    task.status = "running"  # 未提交修改
    await FileContext(store).rollback()  # 丢弃内存修改，从磁盘重载
    got = await table.get(task.id)
    assert got.status == "pending"


async def test_concurrent_appends_serialized():
    store = get_store()

    async def _append(i: int):
        await store.jsonl_append("sessions/conc.jsonl", {"i": i})

    await asyncio.gather(*[_append(i) for i in range(20)])
    records = await store.jsonl_list("sessions/conc.jsonl")
    assert len(records) == 20  # 无丢失/无半行


async def test_register_before_load_survives_ensure_loaded(tmp_path):
    """会话行丢失根因回归（2026-08-23 定位）：表未加载时 register（重启后首请求窗口，
    磁盘已有历史数据），并发请求触发的 _ensure_loaded 不得整体覆盖丢行——否则 flush
    落盘无此行、重启 40401。

    修复前：register 不加载磁盘 → _ensure_loaded 读磁盘旧 items 整体覆盖 _items → 新行消失。
    真实复现路径：服务重启后首个断流请求创建会话（a5c709f8）→ 并发完整流请求 touch/list
    触发加载 → 行从内存消失 → 磁盘无 → 重启后会话 40401。
    """
    from app.storage.file.tables import FileTable
    from app.storage.models.conversation import Conversation

    # 预置磁盘数据（模拟重启前已有历史会话）
    old = FileTable(tmp_path, "conversations.json", Conversation)
    conv0 = Conversation(user_id=uuid.UUID(int=0), agent_id=uuid.UUID(int=0), title="历史会话")
    old.register(conv0)
    await old.flush()
    # 新表实例 = 服务重启（表未加载）
    table = FileTable(tmp_path, "conversations.json", Conversation)
    conv = Conversation(user_id=uuid.UUID(int=0), agent_id=uuid.UUID(int=0), title="首会话")
    table.register(conv)  # 未加载窗口 register 新行
    await table.list()  # 并发请求查询触发 _ensure_loaded（修复前此处覆盖丢新行）
    await table.flush()
    got = await table.get(conv.id)
    assert got is not None  # 修复前为 None（行被覆盖丢失）
    # 磁盘重读（模拟重启）：行必须还在，历史行不丢
    fresh = FileTable(tmp_path, "conversations.json", Conversation)
    assert (await fresh.get(conv.id)) is not None
    assert (await fresh.get(conv0.id)) is not None


async def test_from_dict_restores_uuid_and_datetime_fields():
    """回归（P6 review 修复）：模型无 future import → 磁盘 round-trip 后 uuid/datetime 字段
    还原为类型对象（否则 org_id/workspace_id 变 str，工作区隔离/记忆作用域过滤失效）。"""
    import uuid as _uuid

    from app.storage.models.workspace import Workspace

    ws = Workspace(
        org_id=_uuid.UUID(int=0),
        name="roundtrip",
        root_path="data/workspaces/x",
        created_by=_uuid.UUID(int=1),
    )
    restored = Workspace.from_dict(ws.to_dict())
    assert isinstance(restored.id, _uuid.UUID)
    assert isinstance(restored.org_id, _uuid.UUID)
    assert isinstance(restored.created_by, _uuid.UUID)
    assert isinstance(restored.created_at, type(ws.created_at))


async def test_legacy_task_row_without_recovery_fields_loads_with_none_defaults(tmp_path):
    """旧版 tasks.json 缺少会话/恢复游标字段时仍可正常加载。"""
    from app.storage.file.tables import FileTable

    task = Task(user_id=uuid.UUID(int=0), agent_id=uuid.UUID(int=1), status="pending")
    raw = task.to_dict()
    raw.pop("conversation_id")
    raw.pop("recovery_graph_checkpoint_id")
    (tmp_path / "tasks.json").write_text(
        json.dumps({"version": 1, "items": {str(task.id): raw}}),
        encoding="utf-8",
    )

    table = FileTable(tmp_path, "tasks.json", Task)
    restored = await table.get(task.id)
    assert restored is not None
    assert restored.conversation_id is None
    assert restored.recovery_graph_checkpoint_id is None
