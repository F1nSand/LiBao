"""T4 执行器测试：重试（指数退避）、幂等去重、沙盒守卫、校验/超时不重试。纯单元，无 DB。"""
from __future__ import annotations

import time

from app.tools import executor
from app.tools.registry import ToolSpec
from app.tools.sandbox import SandboxLevel


def _spec(**kw) -> ToolSpec:
    base = {
        "id": "t_x",
        "name": "x",
        "description": "d",
        "params_schema": {"type": "object", "properties": {}, "required": []},
    }
    base.update(kw)
    return ToolSpec(**base)


async def test_retry_success_after_two_failures():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return {"ok": True}

    result = await executor.execute(_spec(max_retries=2, handler=handler), {})
    assert result.ok is True
    assert result.retries == 2
    assert calls["n"] == 3


async def test_retry_all_fail():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        raise RuntimeError("always fails")

    result = await executor.execute(_spec(max_retries=2, handler=handler), {})
    assert result.ok is False
    assert result.retries == 2
    assert calls["n"] == 3
    assert "RuntimeError" in result.error


async def test_validation_failure_not_retried():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        return {"ok": True}

    spec = ToolSpec(
        id="t_req", name="req", description="d",
        params_schema={"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        max_retries=3, handler=handler,
    )
    result = await executor.execute(spec, {})
    assert result.ok is False
    assert "参数校验失败" in result.error
    assert calls["n"] == 0  # 校验失败不触发 handler，更不重试


async def test_timeout_not_retried():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        time.sleep(1)

    result = await executor.execute(_spec(max_retries=3, timeout_ms=50, handler=handler), {})
    assert result.ok is False
    assert "超时" in result.error
    assert result.retries == 0
    assert calls["n"] == 1  # 超时直接返回，不重试


async def test_idempotent_dedupes_same_input():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        return {"result": calls["n"]}

    spec = _spec(idempotent=True, handler=handler)
    r1 = await executor.execute(spec, {})
    r2 = await executor.execute(spec, {})
    assert calls["n"] == 1  # 同指纹去重
    assert r1.output == r2.output
    assert r2.duration_ms == r1.duration_ms  # 命中缓存（时长一致）


async def test_idempotent_explicit_key_differs():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        return {"result": calls["n"]}

    spec = _spec(idempotent=True, handler=handler)
    await executor.execute(spec, {"idempotency_key": "k1"})
    await executor.execute(spec, {"idempotency_key": "k2"})
    assert calls["n"] == 2  # 显式 key 不同 → 不命中


async def test_non_idempotent_not_cached():
    calls = {"n": 0}

    def handler(**kw):
        calls["n"] += 1
        return {"result": calls["n"]}

    spec = _spec(idempotent=False, handler=handler)
    await executor.execute(spec, {})
    await executor.execute(spec, {})
    assert calls["n"] == 2  # 非幂等不缓存


async def test_sandbox_guard_rejects_docker():
    def handler(**kw):
        return {"ok": True}

    result = await executor.execute(_spec(sandbox=SandboxLevel.DOCKER, handler=handler), {})
    assert result.ok is False
    assert "沙盒执行暂未实现" in result.error
