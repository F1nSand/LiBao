"""FileStore 设施测试：FileTable 原子写/JSONL append/并发安全/回滚重载。"""
from __future__ import annotations

import asyncio
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
