"""B2 live-tail Redis 测试（requires_redis）：订阅 → 推送 → 事件 + 终态 __end__ 哨兵。"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from app.services.task import push_event, subscribe, unsubscribe
from app.storage.redis import close_redis, init_redis
from tests.conftest import requires_redis

pytestmark = requires_redis


@pytest.fixture
async def tail_fixture():
    init_redis()
    yield
    await close_redis()


async def test_subscribe_pushes_and_terminal_sentinel(tail_fixture):
    task_id = f"t-{uuid.uuid4().hex[:8]}"
    q = await subscribe(task_id)
    try:
        await push_event(task_id, "status", {"status": "running"})
        event_type, payload = await asyncio.wait_for(q.get(), timeout=2)
        assert event_type == "status"
        assert payload == {"status": "running"}
        await push_event(task_id, "done", {"status": "done"})
        event_type, payload = await asyncio.wait_for(q.get(), timeout=2)
        assert event_type == "done"
        sentinel = await asyncio.wait_for(q.get(), timeout=2)
        assert sentinel is None  # 终态 __end__ 哨兵关闭流
    finally:
        await unsubscribe(task_id, q)


async def test_multiple_subscribers_all_receive(tail_fixture):
    task_id = f"t-{uuid.uuid4().hex[:8]}"
    q1 = await subscribe(task_id)
    q2 = await subscribe(task_id)
    try:
        await push_event(task_id, "status", {"status": "running"})
        e1, _ = await asyncio.wait_for(q1.get(), timeout=2)
        e2, _ = await asyncio.wait_for(q2.get(), timeout=2)
        assert e1 == e2 == "status"
    finally:
        await unsubscribe(task_id, q1)
        await unsubscribe(task_id, q2)
