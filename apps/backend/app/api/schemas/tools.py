"""工具 schema（《02》接口契约 §5.5）。创建默认 enabled=false（默认关闭原则，由服务层强制）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.tools.sandbox import SandboxLevel


class CreateToolRequest(BaseModel):
    name: str
    description: str = ""
    params_schema: dict[str, Any] | None = None
    tool_type: str = "execution"
    require_confirm: bool = False
    idempotent: bool = False
    sandbox: SandboxLevel = SandboxLevel.NONE
    timeout_ms: int = Field(default=30000, ge=1)
    max_concurrency: int = Field(default=1, ge=1)


class UpdateToolRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    params_schema: dict[str, Any] | None = None
    tool_type: str | None = None
    require_confirm: bool | None = None
    idempotent: bool | None = None
    sandbox: SandboxLevel | None = None
    timeout_ms: int | None = Field(default=None, ge=1)
    max_concurrency: int | None = Field(default=None, ge=1)


class ToolToggleRequest(BaseModel):
    enabled: bool


class ToolTestRequest(BaseModel):
    params: dict[str, Any] = {}


class McpRegisterRequest(BaseModel):
    """MCP 源注册（《02》接口契约 §5.5 / FrontEnd McpRegisterRequest）。name 可选，缺省派生。"""

    name: str | None = None
    url_or_command: str  # 命令（stdio）或 http(s) URL
    headers: dict[str, str] | None = None
    enable: bool | None = None  # server 连接启用；工具本身默认关闭
