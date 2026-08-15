"""T2 MCP 连接层测试（纯单元，monkeypatch/fake session，不连真实 server）。

覆盖：传输判定（stdio/http）、名字派生、slug 化、工具发现、call 文本拼接、is_error、异常包装。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent, Tool

from app.tools.mcp_client import (
    McpCallError,
    McpConnectError,
    McpConnection,
    McpToolInfo,
    _split_command,
    derive_server_name,
    extract_text,
    parse_transport,
    slugify,
)

# ---- 传输判定 / 命名派生 / slug（纯函数）----

def test_parse_transport_http():
    kind, cfg = parse_transport("https://demo.mcp.local/mcp")
    assert kind == "http"
    assert cfg["url"] == "https://demo.mcp.local/mcp"
    assert "command" not in cfg


def test_parse_transport_stdio():
    kind, cfg = parse_transport("npx @modelcontextprotocol/server-everything")
    assert kind == "stdio"
    assert cfg["command"] == "npx @modelcontextprotocol/server-everything"


def test_derive_server_name_url():
    assert derive_server_name("https://everything.mcp.local/mcp") == "everything"
    assert derive_server_name("http://www.example.com") == "example"


def test_derive_server_name_command():
    # 去已知前缀 token，取剩余 token 的 basename
    assert derive_server_name("npx @modelcontextprotocol/server-everything") == "server-everything"
    assert derive_server_name("python examples/mcp_demo_server.py") == "mcp_demo_server"
    assert derive_server_name("uv run demo_server") == "demo_server"


def test_derive_server_name_fallback():
    assert derive_server_name("python3") == "mcp-server"  # 全为前缀 → 兜底


def test_slugify():
    assert slugify("Add Numbers!") == "add_numbers_"
    assert slugify("  UPPER Case  ") == "upper_case"  # 首尾空白 strip
    assert slugify("a-b_c") == "a-b_c"  # 保留 - _


# ---- 连接 / 工具发现 / 调用（fake session 注入）----

class FakeStreams:
    """模拟 transport 异步上下文管理器（避免 stdio_client 起真实子进程）。"""

    def __init__(self):
        self.entered = False

    async def __aenter__(self):
        self.entered = True
        return ("fake_read", "fake_write")

    async def __aexit__(self, *args):
        self.entered = False


class FakeSession:
    """模拟 mcp ClientSession：__aenter__/initialize/list_tools/call_tool/__aexit__。"""

    def __init__(self, tools=None, call_result=None, *, fail_initialize=False, raise_on_call=False):
        self.tools = tools or []
        self.call_result = call_result or CallToolResult(content=[], is_error=False)
        self.fail_initialize = fail_initialize
        self.raise_on_call = raise_on_call
        self.entered = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *args):
        self.entered = False

    async def initialize(self):
        if self.fail_initialize:
            raise RuntimeError("init boom")

    async def list_tools(self):
        return SimpleNamespace(tools=self.tools)

    async def call_tool(self, name, arguments):
        if self.raise_on_call:
            raise RuntimeError("call boom")
        return self.call_result


def _conn(session: FakeSession) -> McpConnection:
    cfg = SimpleNamespace(transport="stdio", command="python demo.py", url=None, headers=None)
    return McpConnection(
        cfg, streams_factory=lambda: FakeStreams(), session_factory=lambda read, write: session
    )


async def test_connect_and_list_tools():
    sess = FakeSession(
        tools=[
            Tool(name="echo", description="回声", input_schema={"type": "object", "properties": {}}),
            Tool(name="add", description=None, input_schema={"type": "object", "properties": {}}),
        ]
    )
    conn = _conn(sess)
    await conn.connect()
    tools = await conn.list_tools()
    assert len(tools) == 2
    assert isinstance(tools[0], McpToolInfo)
    assert tools[0].name == "echo"
    assert tools[0].description == "回声"
    assert tools[0].input_schema["type"] == "object"
    assert tools[1].description == ""  # None → 空串兜底
    assert tools[1].input_schema == {"type": "object", "properties": {}}  # schema 原样保真（OA7 不静默注入）


async def test_call_tool_text_join():
    sess = FakeSession(
        call_result=CallToolResult(
            content=[TextContent(type="text", text="a"), TextContent(type="text", text="b")],
            is_error=False,
        )
    )
    conn = _conn(sess)
    await conn.connect()
    ok, text = await conn.call_tool("echo", {"text": "x"})
    assert ok is True
    assert text == "a\nb"


async def test_call_tool_is_error():
    sess = FakeSession(call_result=CallToolResult(content=[TextContent(type="text", text="boom")], is_error=True))
    conn = _conn(sess)
    await conn.connect()
    ok, text = await conn.call_tool("bad", {})
    assert ok is False
    assert text == "boom"


async def test_call_tool_exception_raises_for_breaker():
    # I2：调用期传输异常 → 抛 McpCallError（manager 计数熔断），is_error 业务失败不走此路径
    sess = FakeSession(raise_on_call=True)
    conn = _conn(sess)
    await conn.connect()
    with pytest.raises(McpCallError) as exc:
        await conn.call_tool("bad", {})
    assert "call boom" in str(exc.value)


def test_split_command_windows_path():
    # M3：Windows 绝对路径不吞反斜杠（shlex 会把 C:\mcp\server.py 当转义吃掉）
    assert _split_command(r"python C:\mcp\server.py") == ["python", r"C:\mcp\server.py"]
    assert _split_command("npx @modelcontextprotocol/server-everything") == [
        "npx",
        "@modelcontextprotocol/server-everything",
    ]


def test_derive_server_name_windows_path():
    assert derive_server_name(r"C:\mcp\server.py") == "server"


async def test_connect_initialize_failure_raises():
    sess = FakeSession(fail_initialize=True)
    conn = _conn(sess)
    with pytest.raises(McpConnectError) as exc:
        await conn.connect()
    assert "init boom" in str(exc.value)


def test_extract_text_non_text_block_json_fallback():
    result = CallToolResult(
        content=[ImageContent(type="image", data="eA==", mimeType="image/png")], is_error=False
    )
    text = extract_text(result)
    assert '"image"' in text  # 非文本块 json 化兜底（pydantic model_dump）
