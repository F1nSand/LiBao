"""MCP 源连接配置数据访问（《02》数据模型 §3.5 补充）。软删过滤。文件化：.agent/mcp_servers.json。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.storage.file.store import get_store
from app.storage.models.mcp_server import McpServer


class McpServerRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.table = get_store().table("mcp_servers")

    async def get_by_id_org(self, org_id: uuid.UUID, server_id: uuid.UUID) -> McpServer | None:
        row = await self.table.get(server_id)
        if row is None or row.deleted_at is not None:
            return None
        return row

    async def get_by_id_including_deleted(self, server_id: uuid.UUID) -> McpServer | None:
        """含软删（启动重建需判断 deleted_at）。"""
        return await self.table.get(server_id)

    async def get_by_org_name(self, org_id: uuid.UUID, name: str) -> McpServer | None:
        rows = await self.table.list(
            filter_fn=lambda s: s.name == name and s.deleted_at is None, limit=1
        )
        return rows[0] if rows else None

    async def list_for_org(self, org_id: uuid.UUID) -> list[McpServer]:
        return await self.table.list(
            filter_fn=lambda s: s.deleted_at is None, sort_key=lambda s: s.created_at, desc=True
        )

    async def count_tools(self, org_id: uuid.UUID, mcp_source: str) -> int:
        tools = get_store().table("tool_definitions")
        return await tools.count(
            filter_fn=lambda t: t.mcp_source == mcp_source and t.deleted_at is None
        )

    def create(
        self,
        *,
        org_id: uuid.UUID,
        name: str,
        transport: str,
        command: str | None,
        url: str | None,
        headers: dict | None,
        enabled: bool = True,
    ) -> McpServer:
        row = McpServer(
            org_id=org_id,
            name=name,
            transport=transport,
            command=command,
            url=url,
            headers=headers,
            enabled=enabled,
        )
        self.table.register(row)
        return row

    async def soft_delete(self, row: McpServer) -> None:
        row.deleted_at = datetime.now(UTC)
