"""T3 熔断器 + MCPManager 测试（纯单元，fake connection 注入，不连真实 server）。

覆盖：熔断 OPEN 拒绝、冷却后 HALF_OPEN 放行、惰性连接 + 并发锁、失败计数开闸、
validate 真连接（fake）、close_all 清理。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.tools.mcp_client import McpConnConfig, McpToolInfo
from app.tools.mcp_manager import CircuitBreaker, MCPManager


# ---- 熔断器 ----

def test_breaker_opens_after_threshold():
    b = CircuitBreaker(threshold=3, cooldown_s=60)
    assert not b.is_open()
    for _ in range(3):
        b.record_failure()
    assert b.is_open()


def test_breaker_cooldown_allows_half_open():
    b = CircuitBreaker(threshold=2, cooldown_s=0.01)
    b.record_failure()
    b.record_failure()
    assert b.is_open()
    asyncio.run(asyncio.sleep(0.02))
    assert not b.is_open()  # 冷却结束
    assert b.allow() is True  # HALF_OPEN 放行一次
    assert b.allow() is False  # 放行后拒绝（等待 success/failure 复位）


def test_breaker_success_resets():
    b = CircuitBreaker(threshold=2, cooldown_s=60)
    b.record_failure()
    b.record_success()
    b.record_failure()
    assert not b.is_open()  # 连续计数被 success 复位


# ---- MCPManager ----

class FakeConn:
    """模拟 McpConnection：connect/list_tools/call_tool/close。"""

    def __init__(self, *, fail_connect=False, fail_calls=0, result=(True, "ok")):
        self.fail_connect = fail_connect
        self.fail_calls = fail_calls
        self.result = result
        self.call_count = 0
        self.connect_count = 0
        self.closed = False

    async def connect(self):
        self.connect_count += 1
        if self.fail_connect:
            raise RuntimeError("connect boom")

    async def list_tools(self):
        return [McpToolInfo(name="echo", description="E", input_schema={})]

    async def call_tool(self, name, args):
        self.call_count += 1
        if self.call_count <= self.fail_calls:
            raise RuntimeError("call boom")
        return self.result

    async def close(self):
        self.closed = True


def _cfg() -> McpConnConfig:
    return McpConnConfig(transport="stdio", command="python demo.py")


def _mgr_with(conn: FakeConn) -> MCPManager:
    mgr = MCPManager()
    mgr._conn_factory = lambda server_id, cfg: conn
    return mgr


async def test_manager_breaker_open_returns_error():
    mgr = _mgr_with(FakeConn())
    mgr._breakers["s1"] = CircuitBreaker(1, 60)
    mgr._breakers["s1"].record_failure()
    ok, text = await mgr.call("s1", _cfg(), "echo", {})
    assert ok is False
    assert "熔断" in text
    # 熔断期间不再触碰连接
    assert mgr._connections.get("s1") is None


async def test_manager_lazy_connect_and_success():
    conn = FakeConn()
    mgr = _mgr_with(conn)
    ok, text = await mgr.call("s1", _cfg(), "echo", {})
    assert ok is True
    assert text == "ok"
    assert mgr._connections["s1"] is conn
    assert conn.connect_count == 1


async def test_manager_failure_opens_breaker():
    conn = FakeConn(fail_calls=3)  # 3 次失败（阈值 3）→ 第 4 次直接熔断
    mgr = _mgr_with(conn)
    for _ in range(3):
        ok, text = await mgr.call("s1", _cfg(), "echo", {})
        assert ok is False and "boom" in text
    ok, text = await mgr.call("s1", _cfg(), "echo", {})
    assert ok is False
    assert "熔断" in text
    assert conn.call_count == 3  # 熔断期不再执行


async def test_manager_connect_failure_opens_breaker():
    mgr = _mgr_with(FakeConn(fail_connect=True))
    for _ in range(3):
        ok, _ = await mgr.call("s1", _cfg(), "echo", {})
        assert ok is False
    ok, text = await mgr.call("s1", _cfg(), "echo", {})
    assert ok is False and "熔断" in text


async def test_manager_validate_connects_and_closes():
    conn = FakeConn()
    mgr = _mgr_with(conn)
    tools = await mgr.validate(_cfg())
    assert tools[0].name == "echo"
    assert conn.connect_count == 1
    assert conn.closed is True  # 验证后立即关闭（不驻留子进程）


async def test_manager_close_all():
    conn = FakeConn()
    mgr = _mgr_with(conn)
    mgr._connections["s2"] = conn
    await mgr.close_all()
    assert mgr._connections == {}


async def test_manager_concurrent_connect_single_lock():
    # 并发 call 同一 server → 只 connect 一次（锁串行化）
    conn = FakeConn()
    mgr = _mgr_with(conn)
    results = await asyncio.gather(*[mgr.call("s1", _cfg(), "echo", {}) for _ in range(5)])
    assert all(r[0] for r in results)
    assert conn.connect_count == 1


async def test_manager_validate_failure_raises():
    mgr = _mgr_with(FakeConn(fail_connect=True))
    with pytest.raises(Exception) as exc:
        await mgr.validate(_cfg())
    assert "connect boom" in str(exc.value)


async def test_manager_breaker_resets_after_success():
    # 熔断冷却后 HALF_OPEN 放行，成功 → 复位 CLOSED
    conn = FakeConn(fail_calls=1)
    mgr = _mgr_with(conn)
    mgr._breakers["s1"] = CircuitBreaker(1, 0.01)
    ok, _ = await mgr.call("s1", _cfg(), "echo", {})
    assert ok is False
    await asyncio.sleep(0.02)  # 冷却
    ok, text = await mgr.call("s1", _cfg(), "echo", {})
    assert ok is True and text == "ok"
    ok, text = await mgr.call("s1", _cfg(), "echo", {})
    assert ok is True  # CLOSED，直接放行
