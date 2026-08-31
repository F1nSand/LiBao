"""MCP demo server（M2.5 端到端验证用）。

mcp SDK 2.0 低层 Server：echo / add 两个工具。stdio 默认；--http 时用 streamable_http_app 起 HTTP 传输。

用法：
  python examples/mcp_demo_server.py                 # stdio（注册 url_or_command 用）
  python examples/mcp_demo_server.py --http --port 9000   # HTTP（注册 http://127.0.0.1:9000/mcp 用）
"""
from __future__ import annotations

import argparse
import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent, Tool

TOOLS = [
    Tool(
        name="echo",
        description="回显输入文本（演示用）",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要回显的文本"}},
            "required": ["text"],
        },
    ),
    Tool(
        name="add",
        description="两个数字相加",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    ),
]


async def _on_list_tools(ctx, params=None) -> ListToolsResult:
    return ListToolsResult(tools=TOOLS)


async def _on_call_tool(ctx, params: CallToolRequestParams) -> CallToolResult:
    if params.name == "echo":
        text = (params.arguments or {}).get("text", "")
        return CallToolResult(content=[TextContent(type="text", text=f"echo: {text}")], is_error=False)
    if params.name == "add":
        args = params.arguments or {}
        value = int(args.get("a", 0)) + int(args.get("b", 0))
        return CallToolResult(content=[TextContent(type="text", text=str(value))], is_error=False)
    return CallToolResult(content=[TextContent(type="text", text=f"未知工具: {params.name}")], is_error=True)


server = Server("demo", on_list_tools=_on_list_tools, on_call_tool=_on_call_tool)


async def _run_stdio() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP demo server")
    parser.add_argument("--http", action="store_true", help="用 streamable HTTP 传输")
    parser.add_argument("--port", type=int, default=9000)
    args = parser.parse_args()
    if args.http:
        import uvicorn

        uvicorn.run(server.streamable_http_app(), host="127.0.0.1", port=args.port)
    else:
        asyncio.run(_run_stdio())


if __name__ == "__main__":
    main()
