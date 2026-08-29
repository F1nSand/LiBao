from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.errors import AppError
from app.services.serializers import serialize_task
from app.services.task import TaskService
from app.storage.file.store import get_store
from app.storage.models.task import Task
from app.storage.repositories.task import TaskRepository


def test_resolve_execution_thread_prefers_pending_then_chat_conversation():
    task_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    assert (
        TaskService.resolve_execution_thread(
            SimpleNamespace(
                id=task_id,
                input={"conversation_id": str(conversation_id)},
                pending_confirm={"thread_id": "pending-thread"},
            )
        )
        == "pending-thread"
    )
    assert (
        TaskService.resolve_execution_thread(
            SimpleNamespace(id=task_id, input={"conversation_id": str(conversation_id)}, pending_confirm=None)
        )
        == str(conversation_id)
    )
    assert TaskService.resolve_execution_thread(SimpleNamespace(id=task_id, input={}, pending_confirm=None)) == str(
        task_id
    )


@pytest.mark.asyncio
async def test_recover_precheck_is_idempotent_and_caps_attempts():
    user_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    async with get_store().session() as db:
        task = await TaskRepository(db).create(user_id=user_id, agent_id=agent_id, input={"message": "retry"})
        task.error = {
            "code": 60008,
            "message": "peer closed connection",
            "kind": "llm_transport",
            "retryable": True,
            "recoverable": True,
        }
        task.status = "failed"
        await db.commit()
        service = TaskService()

        key = "recover-key-1"
        assert await service.recover_precheck(db, task, key) == "start"
        assert task.status == "running"
        assert await service.recover_precheck(db, task, key) == "already_running"

        for index in (2, 3):
            task.status = "failed"
            await db.commit()
            assert await service.recover_precheck(db, task, f"recover-key-{index}") == "start"

        task.status = "failed"
        await db.commit()
        with pytest.raises(AppError, match="恢复次数"):
            await service.recover_precheck(db, task, "recover-key-4")


@pytest.mark.asyncio
async def test_serialize_task_exposes_structured_recovery_error_and_cursor():
    task = Task(
        user_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        status="failed",
        input={},
        error={"code": 60008, "kind": "llm_transport", "retryable": True, "recoverable": True},
        last_event_seq=7,
        recovery_attempts=1,
    )
    payload = serialize_task(task)
    assert payload["error"]["recoverable"] is True
    assert payload["last_event_seq"] == 7
    assert payload["recovery_attempts"] == 1
