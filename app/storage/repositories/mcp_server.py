"""MCP 源连接配置数据访问（docs 04 §3.5 补充）。软删过滤；org 数据隔离。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.mcp_server import McpServer
from app.storage.models.tool_definition import ToolDefinition


class McpServerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id_org(self, org_id: uuid.UUID, server_id: uuid.UUID) -> McpServer | None:
        """org 内未软删的 server。"""
        stmt = select(McpServer).where(
            McpServer.org_id == org_id, McpServer.id == server_id, McpServer.deleted_at.is_(None)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_including_deleted(self, server_id: uuid.UUID) -> McpServer | None:
        """含软删（启动重建需判断 deleted_at）。"""
        return await self.session.get(McpServer, server_id)

    async def get_by_org_name(self, org_id: uuid.UUID, name: str) -> McpServer | None:
        stmt = select(McpServer).where(
            McpServer.org_id == org_id, McpServer.name == name, McpServer.deleted_at.is_(None)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_org(self, org_id: uuid.UUID) -> list[McpServer]:
        stmt = (
            select(McpServer)
            .where(McpServer.org_id == org_id, McpServer.deleted_at.is_(None))
            .order_by(McpServer.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def count_tools(self, org_id: uuid.UUID, mcp_source: str) -> int:
        stmt = select(func.count()).select_from(ToolDefinition).where(
            ToolDefinition.org_id == org_id,
            ToolDefinition.mcp_source == mcp_source,
            ToolDefinition.deleted_at.is_(None),
        )
        return int((await self.session.execute(stmt)).scalar_one())

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
        self.session.add(row)
        return row

    async def soft_delete(self, row: McpServer) -> None:
        row.deleted_at = datetime.now(UTC)
        self.session.add(row)
