"""MCP 客户端连接层（docs 01 §7.2 / docs 03 §5.5）。

mcp SDK 2.0：stdio 走 stdio_client(StdioServerParameters)，HTTP 走 streamable_http_client
（headers 经 httpx2.AsyncClient 注入）；Tool.input_schema / CallToolResult.is_error 为 snake_case。
连接句柄 + ClientSession 驻留，可复连（close 后可再 connect）。
"""
from __future__ import annotations

import json
import os
import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters


@dataclass(frozen=True)
class McpToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class McpConnConfig:
    """连接配置（与 mcp_servers 行一一对应）。"""

    transport: str  # "stdio" | "http"
    command: str | None = None  # stdio 原始命令串（含参数）
    url: str | None = None  # http 端点
    headers: dict[str, str] | None = None


class McpConnectError(Exception):
    """MCP 连接/初始化失败（注册验证与执行路径共用；注册侧转 50201）。"""


class McpCallError(Exception):
    """MCP 调用期传输/协议异常（stdio 流死亡、SDK 超时等）——熔断计数依据。

    is_error=True 的业务失败不走此异常（那是工具的失败，不是源的故障）。
    """


def _split_command(cmd: str) -> list[str]:
    """命令分词：Windows 路径（盘符/反斜杠）按空白切分，避免 shlex 吞反斜杠；否则 shlex。"""
    if sys.platform == "win32" and (":" in cmd or "\\" in cmd):
        return cmd.split()
    return shlex.split(cmd)


_PREFIX_TOKENS = {"npx", "uvx", "uv", "python", "python3"}
_SUFFIXES = (".py", ".js", ".ts", ".sh")


def parse_transport(url_or_command: str) -> tuple[str, dict[str, Any]]:
    """传输判定：http(s):// 开头 → http；否则按命令 → stdio。"""
    if url_or_command.startswith(("http://", "https://")):
        return "http", {"url": url_or_command}
    return "stdio", {"command": url_or_command}


def derive_server_name(url_or_command: str) -> str:
    """server 名派生：URL → hostname 主标签；命令 → 去已知前缀 token 后取 basename；兜底 mcp-server。"""
    if url_or_command.startswith(("http://", "https://")):
        host = url_or_command.split("://", 1)[1].split("/", 1)[0]
        label = host.removeprefix("www.").split(".")[0]
        return slugify(label) or "mcp-server"
    # 去前缀包装 token（npx/uvx/uv/python…），取最后一个剩余 token 的 basename（真实入口点）
    tokens = [t for t in _split_command(url_or_command) if t not in _PREFIX_TOKENS]
    if not tokens:
        return "mcp-server"
    name = os.path.basename(tokens[-1].rstrip("/"))
    for suffix in _SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return slugify(name) or "mcp-server"


def slugify(s: str) -> str:
    """slug 化：strip 后小写 + 仅保留 [a-z0-9_-]，其余转 _。"""
    s = s.strip()
    return "".join(ch.lower() if ch.isalnum() or ch in "-_" else "_" for ch in s)


def extract_text(result: Any) -> str:
    """CallToolResult → 文本：TextContent 用换行拼接；其余块类型 json 化兜底（pydantic 模型经 model_dump）。"""
    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        if getattr(block, "type", "") == "text":
            parts.append(block.text)
        else:
            try:
                dump = block.model_dump() if hasattr(block, "model_dump") else block
                parts.append(json.dumps(dump, ensure_ascii=False, default=str))
            except (TypeError, ValueError):
                parts.append(str(block))
    return "\n".join(parts)


class McpConnection:
    """单 MCP server 连接：transport 句柄 + ClientSession。可复连。"""

    def __init__(
        self,
        cfg: McpConnConfig,
        *,
        streams_factory: Callable[[], Any] | None = None,
        session_factory: Callable[[Any, Any], Any] | None = None,
    ) -> None:
        self.cfg = cfg
        self._streams_factory = streams_factory  # 测试注入点（fake transport，防起真实子进程）
        self._session_factory = session_factory  # 测试注入点（fake session）
        self._streams: Any = None
        self._session: Any = None
        self._http_client: Any = None  # 自建 httpx2 client（需自行关闭）

    async def connect(self) -> None:
        if self._session is not None:
            return
        try:
            if self._streams_factory is not None:
                self._streams = self._streams_factory()
            elif self.cfg.transport == "http":
                from mcp.client.streamable_http import streamable_http_client

                if self.cfg.headers:
                    import httpx2

                    self._http_client = httpx2.AsyncClient(headers=self.cfg.headers)
                self._streams = streamable_http_client(self.cfg.url, http_client=self._http_client)
            else:
                from mcp.client.stdio import stdio_client

                parts = _split_command(self.cfg.command or "")
                self._streams = stdio_client(
                    StdioServerParameters(command=parts[0] if parts else "python", args=parts[1:])
                )
            read, write = await self._streams.__aenter__()
            if self._session_factory is not None:
                self._session = self._session_factory(read, write)
            else:
                self._session = ClientSession(read, write)
            await self._session.__aenter__()
            await self._session.initialize()
        except Exception as exc:  # noqa: BLE001  统一包装为 McpConnectError（注册侧 50201 / 执行侧熔断）
            await self.close()
            raise McpConnectError(str(exc)) from exc

    async def list_tools(self) -> list[McpToolInfo]:
        res = await self._session.list_tools()
        out: list[McpToolInfo] = []
        for t in res.tools:
            schema = t.input_schema
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}, "required": []}
            out.append(McpToolInfo(name=t.name, description=t.description or "", input_schema=schema))
        return out

    async def call_tool(self, name: str, args: dict[str, Any]) -> tuple[bool, str]:
        """调用远程工具 → (ok, 文本)。传输/协议异常抛 McpCallError（熔断计数）；
        is_error=True 是工具的失败（业务错），归一为 (False, 文本) 不参与熔断。"""
        try:
            result = await self._session.call_tool(name, args)
        except Exception as exc:  # noqa: BLE001  源故障 → 上抛给 manager 计数熔断
            raise McpCallError(str(exc)) from exc
        text = extract_text(result)
        return (not bool(getattr(result, "is_error", False)), text)

    async def close(self) -> None:
        if self._session is not None:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001  关闭尽力而为
                pass
            self._session = None
        if self._streams is not None:
            try:
                await self._streams.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
            self._streams = None
        if self._http_client is not None:
            try:
                await self._http_client.aclose()  # 自建 client 必须自行关闭（SDK 不负责）
            except Exception:  # noqa: BLE001
                pass
            self._http_client = None
