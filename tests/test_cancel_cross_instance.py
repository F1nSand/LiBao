"""T3 跨实例 cancel 路由测试（db+redis）：route_cancel 查 claim 归属 → 向持有实例广播 cancel 信号。"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from app.storage.redis import (
    claim_task,
    close_redis,
    get_redis,
    init_redis,
    worker_cancel_channel,
)

from app.orchestration.task_worker import route_cancel
from app.services.task import TaskService
from app.storage.db import init_db, set_sessionmaker
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Org, User
from tests.conftest import requires_db, requires_redis

pytestmark = [requires_db, requires_redis]


@pytest.fixture
async def cross_cancel_fixture():
    init_redis()
    engine, sessionmaker = init_db()
    set_sessionmaker(sessionmaker)
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-cc-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"cc_{uid}", password_hash="hashed", name="T", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=org.id, name="跨实例取消助手", model="fake", system_prompt="你是助手。", tools=[], max_steps=5,
            status="published",
        )
        session.add(agent)
        await session.commit()
    yield sessionmaker, user, agent
    r = get_redis()
    if r is not None:
        await r.delete("task:queue")
    set_sessionmaker(None)
    await close_redis()
    await engine.dispose()


async def test_route_cancel_broadcasts_to_claimed_owner(cross_cancel_fixture):
    """任务被 worker-B claim 且本地无 in-flight → route_cancel 向 worker:cancel:B 广播。"""
    sessionmaker, user, agent = cross_cancel_fixture
    async with get_store().session(sessionmaker) as session:
        task = await TaskService().submit(session, user, agent.id, {"message": "x"})
        task_id = str(task.id)

    await claim_task(task_id, "worker-B")  # 模拟任务运行在实例 worker-B

    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(worker_cancel_channel("worker-B"))

    await route_cancel(task_id)  # 本地无 fut（未 spawn_run），走 claim 路由

    received = None
    async with asyncio.timeout(3):
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                received = msg
                break
    await pubsub.unsubscribe(worker_cancel_channel("worker-B"))
    await pubsub.aclose()
    assert received is not None
    assert json.loads(received["data"]) == {"task_id": task_id}


async def test_route_cancel_no_owner_no_local_is_noop(cross_cancel_fixture):
    """无 claim 且无本地 fut → route_cancel 静默返回（不抛错）。"""
    from app.storage.redis import get_task_owner

    assert await get_task_owner("no-such-task") is None
    await route_cancel("no-such-task")  # 不抛错即可
