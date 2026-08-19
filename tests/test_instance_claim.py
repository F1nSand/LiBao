"""T1 instance id + Redis claim/cancel 命名层测试（requires_redis）。"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.core.instance import get_instance_id
from app.storage.redis import (
    TASK_OWNER_TTL_S,
    claim_task,
    close_redis,
    get_redis,
    get_task_owner,
    init_redis,
    publish_cancel,
    release_task_claim,
    task_owner_key,
    worker_cancel_channel,
)
from tests.conftest import requires_redis

pytestmark = requires_redis


@pytest.fixture
async def claim_fixture():
    init_redis()
    yield
    r = get_redis()
    if r is not None:
        keys = await r.keys("task:owner:*")
        if keys:
            await r.delete(*keys)
    await close_redis()


async def test_get_instance_id_is_stable():
    iid = get_instance_id()
    assert isinstance(iid, str) and len(iid) > 0
    assert get_instance_id() == iid  # 进程级单例


async def test_claim_release_lifecycle(claim_fixture):
    tid, iid = "task-1", "inst-A"
    assert await get_task_owner(tid) is None
    await claim_task(tid, iid)
    assert await get_task_owner(tid) == iid
    await release_task_claim(tid)
    assert await get_task_owner(tid) is None


async def test_claim_ttl_set(claim_fixture):
    tid = "task-2"
    await claim_task(tid, "inst-A")
    r = get_redis()
    ttl = await r.ttl(task_owner_key(tid))
    assert 0 < ttl <= TASK_OWNER_TTL_S


async def test_publish_cancel_channel(claim_fixture):
    iid = "inst-B"
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(worker_cancel_channel(iid))
    await publish_cancel(iid, "task-3")
    received = None
    async with asyncio.timeout(3):
        async for msg in pubsub.listen():
            if msg.get("type") == "message":
                received = msg
                break
    await pubsub.unsubscribe(worker_cancel_channel(iid))
    await pubsub.aclose()
    assert received is not None
    assert json.loads(received["data"]) == {"task_id": "task-3"}


async def test_no_redis_degrades(monkeypatch):
    monkeypatch.setattr("app.storage.redis._redis", None)
    await claim_task("t", "i")  # 不抛错
    assert await get_task_owner("t") is None
    await release_task_claim("t")  # 不抛错
    await publish_cancel("i", "t")  # 不抛错
