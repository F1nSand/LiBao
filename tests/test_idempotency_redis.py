"""B3 幂等 Redis 测试（requires_redis）：执行写 Redis key、TTL≈3600、二次命中缓存。"""
from __future__ import annotations

import pytest

from app.storage.redis import close_redis, get_redis, init_redis
from app.tools import executor
from app.tools.registry import ToolSpec
from tests.conftest import requires_redis

pytestmark = requires_redis


def _spec(handler) -> ToolSpec:
    return ToolSpec(
        id="t_idem",
        name="idem",
        description="d",
        params_schema={"type": "object", "properties": {}, "required": []},
        idempotent=True,
        handler=handler,
    )


@pytest.fixture
async def idem_fixture():
    init_redis()
    yield
    r = get_redis()
    if r is not None:
        keys = await r.keys("idem:*")
        if keys:
            await r.delete(*keys)
    await close_redis()


async def test_execute_writes_redis_and_dedupes(idem_fixture):
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        return {"result": calls["n"]}

    spec = _spec(handler)
    r1 = await executor.execute(spec, {})
    r2 = await executor.execute(spec, {})
    assert calls["n"] == 1  # 二次命中 Redis 缓存，handler 不重复调用
    assert r1.output == r2.output

    r = get_redis()
    keys = await r.keys("idem:t_idem:*")
    assert len(keys) == 1
    ttl = await r.ttl(keys[0])
    assert 0 < ttl <= 3600


async def test_non_serializable_output_falls_back_to_process(idem_fixture):
    """output 非 JSON 可序列化 → 跳过 Redis，回退进程内缓存。"""
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        return object()  # 不可 JSON 序列化

    spec = _spec(handler)
    r1 = await executor.execute(spec, {})
    r2 = await executor.execute(spec, {})
    assert calls["n"] == 1  # 进程内缓存仍去重
    assert r1.output is r2.output

    r = get_redis()
    keys = await r.keys("idem:t_idem:*")
    assert keys == []  # 未写 Redis
