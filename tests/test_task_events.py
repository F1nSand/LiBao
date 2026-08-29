from __future__ import annotations

import uuid

import pytest

from app.services.task import TaskService
from app.services.task_events import (
    list_task_events,
    project_task_payload,
    publish_task_event,
    subscribe_task_events,
    unsubscribe_task_events,
)
from app.storage.file.store import get_store
from app.storage.models.agent import AgentConfig
from app.storage.models.user import User


@pytest.fixture
async def event_task():
    suffix = uuid.uuid4().hex[:8]
    async with get_store().session() as db:
        user = User(username=f"event_{suffix}", password_hash="hashed", name="event", org_id=uuid.UUID(int=0))
        agent = AgentConfig(org_id=uuid.UUID(int=0), name=f"event-agent-{suffix}", model="fake", status="published")
        db.add(user)
        db.add(agent)
        await db.flush()
        task = await TaskService().submit(db, user, agent.id, {"message": "hello"})
        yield task


@pytest.mark.asyncio
async def test_publish_task_event_persists_monotonic_task_seq_across_restart(event_task):
    first = await publish_task_event(str(event_task.id), "status", {"status": "running"})
    second = await publish_task_event(str(event_task.id), "done", {"message": {"content": "ok"}})
    assert first["task_seq"] == 1
    assert second["task_seq"] == 2
    assert [r["task_seq"] for r in await list_task_events(str(event_task.id))] == [1, 2]


def test_project_task_payload_removes_sensitive_and_large_tool_values():
    payload = project_task_payload(
        "tool_result",
        {"tool_call_id": "c1", "input": {"command": "secret"}, "output": "full output", "summary": "short"},
    )
    assert "input" not in payload
    assert "output" not in payload
    assert payload["summary"] == "short"

    error = project_task_payload("error", {"details": {"api_key": "secret", "chunks_received": 3}})
    assert "api_key" not in str(error)
    assert error["details"]["chunks_received"] == 3


@pytest.mark.asyncio
async def test_subscribe_receives_persisted_event_and_terminal_sentinel(event_task):
    queue = await subscribe_task_events(str(event_task.id))
    try:
        await publish_task_event(str(event_task.id), "done", {"message": {"content": "ok"}})
        item = await queue.get()
        assert item[0] == "done" and item[2] == 1
        assert await queue.get() is None
    finally:
        await unsubscribe_task_events(str(event_task.id), queue)
