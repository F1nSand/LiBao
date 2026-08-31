"""2d notifications 测试（DB-backed）：落库/分页/已读/SSE 广播 + 产生源（任务 done、demo_notify）。"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.services.notification import (
    NotificationService,
    maybe_notify_from_tool_results,
    subscribe_notifications,
    unsubscribe_notifications,
)
from app.services.task import TaskService
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, User
from app.storage.repositories.task import TaskRepository


@pytest.fixture
async def notif_fixture():
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"notif_{uid}", password_hash="hashed", name="N", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=uuid.UUID(int=0), name="通知助手", model="fake", system_prompt="x",
            tools=[], max_steps=5, status="published"
        )
        session.add(agent)
        await session.commit()
    yield user, agent


async def test_create_and_list_paged(notif_fixture):
    user, agent = notif_fixture
    async with get_store().session() as session:
        n = await NotificationService().create(session, user.id, "你好", body="body", level="info")
        assert n.id and n.read is False
    async with get_store().session() as session:
        data = await NotificationService().list_paged(session, user.id, 1, 20)
        assert data["total"] == 1
        assert data["items"][0]["title"] == "你好"
        assert data["items"][0]["id"] == str(n.id)
        assert data["items"][0]["read"] is False


async def test_mark_read(notif_fixture):
    user, agent = notif_fixture
    async with get_store().session() as session:
        n = await NotificationService().create(session, user.id, "已读测试")
    async with get_store().session() as session:
        updated = await NotificationService().mark_read(session, user, n.id)
        assert updated.read is True


async def test_sse_push_delivers_to_subscriber(notif_fixture):
    """SSE 广播：订阅后 create 推送帧（Redis Pub/Sub 或进程内回退）。"""
    user, agent = notif_fixture
    q = await subscribe_notifications(str(user.id))
    try:
        async with get_store().session() as session:
            await NotificationService().create(session, user.id, "推送")
        event_type, payload = await asyncio.wait_for(q.get(), timeout=2)  # 桥接异步投递，不能 get_nowait
        assert event_type == "notification"
        assert payload["title"] == "推送"
    finally:
        await unsubscribe_notifications(str(user.id), q)


async def test_task_done_creates_notification(notif_fixture):
    """产生源①：任务 done → 通知。"""
    user, agent = notif_fixture
    async with get_store().session() as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
    async with get_store().session() as session:
        task = await TaskRepository(session).get_by_id(task.id)
        await TaskService().set_done(session, task, {"content": "完成"})
    async with get_store().session() as session:
        data = await NotificationService().list_paged(session, user.id, 1, 20)
        assert data["total"] == 1
        assert data["items"][0]["title"] == "任务已完成"
        assert data["items"][0]["level"] == "success"


async def test_demo_notify_tool_result_creates_notification(notif_fixture):
    """产生源②：demo_notify 确认执行 → 通知。"""
    user, agent = notif_fixture
    final_state = {
        "tool_results": [
            {"tool_name": "tl_demo_notify", "status": "done", "input": {"message": "重要通知", "channel": "default"}}
        ]
    }
    async with get_store().session() as session:
        await maybe_notify_from_tool_results(session, user.id, final_state)
    async with get_store().session() as session:
        data = await NotificationService().list_paged(session, user.id, 1, 20)
        assert data["total"] == 1
        assert data["items"][0]["body"] == "重要通知"
