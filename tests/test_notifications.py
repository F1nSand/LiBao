"""2d notifications 测试（DB-backed）：落库/分页/已读/SSE 广播 + 产生源（任务 done、demo_notify）。"""
from __future__ import annotations

import uuid

import pytest

from app.core.security import hash_password
from app.services.notification import (
    NotificationService,
    maybe_notify_from_tool_results,
    subscribe_notifications,
    unsubscribe_notifications,
)
from app.services.task import TaskService
from app.storage.db import init_db
from app.storage.models import AgentConfig, Org, User
from app.storage.repositories.task import TaskRepository
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
async def notif_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        org = Org(name=f"测试组织-notif-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"notif_{uid}", password_hash=hash_password("x"), name="N", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=org.id, name="通知助手", model="fake", system_prompt="x", tools=[], max_steps=5, status="published"
        )
        session.add(agent)
        await session.commit()
    yield sessionmaker, user, agent
    await engine.dispose()


async def test_create_and_list_paged(notif_fixture):
    sessionmaker, user, agent = notif_fixture
    async with sessionmaker() as session:
        n = await NotificationService().create(session, user.id, "你好", body="body", level="info")
        assert n.id and n.read is False
    async with sessionmaker() as session:
        data = await NotificationService().list_paged(session, user.id, 1, 20)
        assert data["total"] == 1
        assert data["items"][0]["title"] == "你好"
        assert data["items"][0]["id"] == str(n.id)
        assert data["items"][0]["read"] is False


async def test_mark_read(notif_fixture):
    sessionmaker, user, agent = notif_fixture
    async with sessionmaker() as session:
        n = await NotificationService().create(session, user.id, "已读测试")
    async with sessionmaker() as session:
        updated = await NotificationService().mark_read(session, user, n.id)
        assert updated.read is True


async def test_sse_push_delivers_to_subscriber(notif_fixture):
    """SSE 广播：订阅后 create 推送帧（镜像 task live-tail）。"""
    sessionmaker, user, agent = notif_fixture
    q = subscribe_notifications(str(user.id))
    try:
        async with sessionmaker() as session:
            await NotificationService().create(session, user.id, "推送")
        event_type, payload = q.get_nowait()
        assert event_type == "notification"
        assert payload["title"] == "推送"
    finally:
        unsubscribe_notifications(str(user.id), q)


async def test_task_done_creates_notification(notif_fixture):
    """产生源①：任务 done → 通知。"""
    sessionmaker, user, agent = notif_fixture
    async with sessionmaker() as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
    async with sessionmaker() as session:
        task = await TaskRepository(session).get_by_id(task.id)
        await TaskService().set_done(session, task, {"content": "完成"})
    async with sessionmaker() as session:
        data = await NotificationService().list_paged(session, user.id, 1, 20)
        assert data["total"] == 1
        assert data["items"][0]["title"] == "任务已完成"
        assert data["items"][0]["level"] == "success"


async def test_demo_notify_tool_result_creates_notification(notif_fixture):
    """产生源②：demo_notify 确认执行 → 通知。"""
    sessionmaker, user, agent = notif_fixture
    final_state = {
        "tool_results": [
            {"tool_name": "tl_demo_notify", "status": "done", "input": {"message": "重要通知", "channel": "default"}}
        ]
    }
    async with sessionmaker() as session:
        await maybe_notify_from_tool_results(session, user.id, final_state)
    async with sessionmaker() as session:
        data = await NotificationService().list_paged(session, user.id, 1, 20)
        assert data["total"] == 1
        assert data["items"][0]["body"] == "重要通知"
