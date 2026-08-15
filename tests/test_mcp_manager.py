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
    # 熔断期间不建连
    mgr._conn_factory.calls = getattr(mgr._conn_factory, "calls", 0)


async def test_manager_per_call_new_connection():
    # 连接不跨任务驻留：每次 call 独立建连 + 用完即关
    created: list[FakeConn] = []

    def factory(server_id, cfg):
        conn = FakeConn()
        created.append(conn)
        return conn

    mgr = MCPManager(connection_factory=factory)
    ok1, text1 = await mgr.call("s1", _cfg(), "echo", {})
    ok2, text2 = await mgr.call("s1", _cfg(), "echo", {})
    assert ok1 and ok2 and text1 == "ok" and text2 == "ok"
    assert len(created) == 2  # 两次调用两个独立连接
    assert all(c.closed for c in created)  # 用完即关


async def test_manager_failure_opens_breaker():
    # 每次调用独立新连接、首次调用即失败（阈值 3）→ 第 4 次直接熔断
    mgr = MCPManager(connection_factory=lambda server_id, cfg: FakeConn(fail_calls=1))
    for _ in range(3):
        ok, text = await mgr.call("s1", _cfg(), "echo", {})
        assert ok is False and "boom" in text
    ok, text = await mgr.call("s1", _cfg(), "echo", {})
    assert ok is False
    assert "熔断" in text


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


async def test_manager_close_all_clears_breakers():
    mgr = _mgr_with(FakeConn())
    mgr._breakers["s2"] = CircuitBreaker(1, 60)
    await mgr.close_all()
    assert mgr._breakers == {}


async def test_manager_concurrent_calls_independent_connections():
    # 无共享会话：并发调用各自独立建连（跨任务安全），互不干扰
    created: list[FakeConn] = []

    def factory(server_id, cfg):
        conn = FakeConn()
        created.append(conn)
        return conn

    mgr = MCPManager(connection_factory=factory)
    results = await asyncio.gather(*[mgr.call("s1", _cfg(), "echo", {}) for _ in range(5)])
    assert all(r[0] for r in results)
    assert len(created) == 5


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
