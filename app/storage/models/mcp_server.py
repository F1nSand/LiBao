"""MCP 源连接配置实体（《02》后端设计 §7.2 / 《02》数据模型 §3.5 补充）。

tool_definition.mcp_source 存 "mcp:{server_id}" 关联；连接配置（命令/URL/headers）
是启动重建 spec 的唯一依据。
"""

import uuid
from dataclasses import dataclass

from app.storage.file.rows import Row


@dataclass(kw_only=True)
class McpServer(Row):
    org_id: uuid.UUID
    name: str
    transport: str  # stdio | http
    command: str | None = None  # stdio 原始命令串
    url: str | None = None  # http 端点
    headers: dict | None = None
    enabled: bool = True
