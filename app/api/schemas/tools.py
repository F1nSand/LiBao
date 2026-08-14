"""工具 schema（docs 03 §5.5）。创建默认 enabled=false（默认关闭原则，由服务层强制）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class CreateToolRequest(BaseModel):
    name: str
    description: str = ""
    params_schema: dict[str, Any] | None = None
    tool_type: str = "execution"
    require_confirm: bool = False
    idempotent: bool = False
    sandbox: str = "none"
    timeout_ms: int = 30000
    max_concurrency: int = 1


class UpdateToolRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    params_schema: dict[str, Any] | None = None
    tool_type: str | None = None
    require_confirm: bool | None = None
    idempotent: bool | None = None
    sandbox: str | None = None
    timeout_ms: int | None = None
    max_concurrency: int | None = None


class ToolToggleRequest(BaseModel):
    enabled: bool


class ToolTestRequest(BaseModel):
    params: dict[str, Any] = {}


class McpRegisterRequest(BaseModel):
    """MCP 源注册（docs 03 §5.5 / FrontEnd McpRegisterRequest）。name 可选，缺省派生。"""

    name: str | None = None
    url_or_command: str  # 命令（stdio）或 http(s) URL
    headers: dict[str, str] | None = None
    enable: bool | None = None  # server 连接启用；工具本身默认关闭
