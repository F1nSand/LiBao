"""M4 完整版：MCP 会话复用（owner-task 池）测试——同一 server 多次 call 只建连一次。"""
from __future__ import annotations

from app.tools.mcp_client import McpConnConfig
from app.tools.mcp_manager import MCPManager


class FakeConn:
    """假连接：计数 connect/close，call_tool 直接返回。"""

    def __init__(self) -> None:
        self.connect_calls = 0
        self.close_calls = 0
        self.calls: list[tuple[str, dict]] = []

    async def connect(self) -> None:
        self.connect_calls += 1

    async def call_tool(self, name: str, args: dict) -> tuple[bool, str]:
        self.calls.append((name, args))
        return (True, f"result:{name}:{args}")

    async def close(self) -> None:
        self.close_calls += 1


async def test_session_reuse_single_connect():
    created: list[FakeConn] = []

    def factory(server_id: str, cfg: McpConnConfig) -> FakeConn:
        c = FakeConn()
        created.append(c)
        return c

    mgr = MCPManager(connection_factory=factory)
    cfg = McpConnConfig(transport="stdio", command="npx server")
    try:
        ok1, text1 = await mgr.call("srv", cfg, "tool_a", {"a": 1})
        ok2, text2 = await mgr.call("srv", cfg, "tool_b", {})
        assert ok1 and ok2
        assert len(created) == 1, f"会话未复用：新建了 {len(created)} 个连接"
        assert created[0].connect_calls == 1, "同一连接被重复 connect"
        assert created[0].calls == [("tool_a", {"a": 1}), ("tool_b", {})]  # 串行按序执行
        assert text1 == "result:tool_a:{'a': 1}" and text2 == "result:tool_b:{}"
    finally:
        await mgr.close_all()
    assert created[0].close_calls == 1, "close_all 应关闭池中连接"


async def test_close_all_cleans_pool():
    created: list[FakeConn] = []

    def factory(server_id: str, cfg: McpConnConfig) -> FakeConn:
        c = FakeConn()
        created.append(c)
        return c

    mgr = MCPManager(connection_factory=factory)
    cfg = McpConnConfig(transport="http", url="http://localhost:1")
    await mgr.call("s1", cfg, "t", {})
    await mgr.call("s1", cfg, "t2", {})
    assert len(created) == 1
    await mgr.close_all()
    # 关闭后再次 call → 重建连接（新 owner）
    ok, text = await mgr.call("s1", cfg, "t3", {})
    assert ok and len(created) == 2, "close_all 后未重建连接"
    assert created[1].connect_calls == 1
    await mgr.close_all()
