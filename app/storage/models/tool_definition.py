"""工具定义实体（docs 04 §3.5）。

内置工具与 MCP 注册的工具同走 tool_definition 生命周期；enabled 默认关闭（约束优先）。
sandbox: none / docker / microvm；tool_type: perception / execution / collaboration / user_comms / event。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class ToolDefinition(Row):
    org_id: uuid.UUID
    name: str
    description: str = ""
    params_schema: dict = field(default_factory=dict)
    tool_type: str = "execution"
    enabled: bool = False
    require_confirm: bool = False
    idempotent: bool = False
    sandbox: str = "none"
    allowlist: list | None = None
    timeout_ms: int = 30000
    max_concurrency: int = 1
    mcp_source: str | None = None
    mcp_tool_name: str | None = None  # MCP 原始工具名（重建 spec 用）
    version: int = 1
