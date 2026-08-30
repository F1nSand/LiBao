"""进程重启后的 Task 对账与精确 graph cursor 校验。"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services.task_events import list_task_events
from app.services.task_recovery import reconcile_orphaned_tasks
from app.storage.constants import ADMIN_USER
from app.storage.file.store import get_store
from app.storage.repositories.task import TaskRepository


class _CheckpointTuple:
    def __init__(self, checkpoint_id: str) -> None:
        self.config = {"configurable": {"checkpoint_id": checkpoint_id}}
        self.checkpoint = {"id": checkpoint_id}


class _FakeCheckpointer:
    def __init__(self, *, latest_by_thread: dict[str, str], run_bounds: dict[str, str]) -> None:
        self.latest_by_thread = latest_by_thread
        self.run_bounds = run_bounds
        self.calls: list[dict] = []

    async def aget_run_bounds(self, config, code_checkpoint_id):
        self.calls.append({"method": "run_bounds", "config": config, "code": code_checkpoint_id})
        output_id = self.run_bounds.get(str(code_checkpoint_id))
        return "parent", output_id, output_id is not None

    async def aget_tuple(self, config):
        self.calls.append({"method": "tuple", "config": config})
        configurable = config.get("configurable", config)
        thread_id = str(configurable.get("thread_id"))
        checkpoint_id = configurable.get("checkpoint_id")
        selected = str(checkpoint_id) if checkpoint_id is not None else self.latest_by_thread.get(thread_id)
        return _CheckpointTuple(selected) if selected else None


async def _create_task(*, status: str, conversation_id: uuid.UUID | None = None, input: dict | None = None):
    async with get_store().session() as session:
        task = await TaskRepository(session).create(
            user_id=ADMIN_USER.id,
            agent_id=uuid.uuid4(),
            conversation_id=conversation_id,
            input=input or {},
            status=status,
        )
        await session.commit()
        return task


async def test_pending_task_is_failed_without_claiming_a_cursor():
    task = await _create_task(status="pending")
    stats = await reconcile_orphaned_tasks(graph=SimpleNamespace(checkpointer=None))

    async with get_store().session() as session:
        restored = await TaskRepository(session).get_by_id(task.id)
    assert stats == {"scanned": 1, "recovered": 0, "nonrecoverable": 1, "completed": 0}
    assert restored is not None
    assert restored.status == "failed"
    assert restored.recovery_graph_checkpoint_id is None
    assert restored.error["code"] == 60009
    assert restored.error["recoverable"] is False
    events = await list_task_events(str(task.id))
    assert events[-1]["type"] == "error"


async def test_running_chat_task_persists_verified_exact_cursor():
    conversation_id = uuid.uuid4()
    code_checkpoint_id = str(uuid.uuid4())
    graph_checkpoint_id = "graph-output-42"
    task = await _create_task(
        status="running",
        conversation_id=conversation_id,
        input={"conversation_id": str(conversation_id), "checkpoint_id": code_checkpoint_id},
    )
    checkpointer = _FakeCheckpointer(
        latest_by_thread={str(conversation_id): "unrelated-latest"},
        run_bounds={code_checkpoint_id: graph_checkpoint_id},
    )

    stats = await reconcile_orphaned_tasks(graph=SimpleNamespace(checkpointer=checkpointer))

    async with get_store().session() as session:
        restored = await TaskRepository(session).get_by_id(task.id)
    assert stats["recovered"] == 1
    assert restored is not None
    assert restored.status == "failed"
    assert restored.recovery_graph_checkpoint_id == graph_checkpoint_id
    assert restored.error["recoverable"] is True
    explicit = [call for call in checkpointer.calls if call["method"] == "tuple"][-1]
    assert explicit["config"]["configurable"]["checkpoint_id"] == graph_checkpoint_id


async def test_running_background_task_uses_task_thread_and_explicit_cursor():
    task = await _create_task(status="running", input={"message": "background"})
    graph_checkpoint_id = "background-output-7"
    checkpointer = _FakeCheckpointer(
        latest_by_thread={str(task.id): graph_checkpoint_id},
        run_bounds={},
    )

    stats = await reconcile_orphaned_tasks(graph=SimpleNamespace(checkpointer=checkpointer))

    async with get_store().session() as session:
        restored = await TaskRepository(session).get_by_id(task.id)
    assert stats["recovered"] == 1
    assert restored is not None and restored.recovery_graph_checkpoint_id == graph_checkpoint_id
    assert any(
        call["method"] == "tuple"
        and call["config"]["configurable"].get("checkpoint_id") == graph_checkpoint_id
        for call in checkpointer.calls
    )
