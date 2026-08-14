"""工具定义数据访问（docs 04 §3.5）。DB 是工具元数据事实源；软删过滤；org 数据隔离。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.tool_definition import ToolDefinition


class ToolDefinitionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, tool_id: uuid.UUID) -> ToolDefinition | None:
        return await self.session.get(ToolDefinition, tool_id)

    async def get_by_org_name(self, org_id: uuid.UUID, name: str) -> ToolDefinition | None:
        stmt = select(ToolDefinition).where(
            ToolDefinition.org_id == org_id,
            ToolDefinition.name == name,
            ToolDefinition.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def name_exists(self, org_id: uuid.UUID, name: str) -> bool:
        stmt = select(ToolDefinition.id).where(
            ToolDefinition.org_id == org_id,
            ToolDefinition.name == name,
            ToolDefinition.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).first() is not None

    async def list_for_org(
        self,
        org_id: uuid.UUID,
        *,
        enabled: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ToolDefinition]:
        stmt = select(ToolDefinition).where(ToolDefinition.org_id == org_id, ToolDefinition.deleted_at.is_(None))
        if enabled is not None:
            stmt = stmt.where(ToolDefinition.enabled.is_(enabled))
        stmt = stmt.order_by(ToolDefinition.created_at.desc()).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars())

    async def count_for_org(self, org_id: uuid.UUID, *, enabled: bool | None = None) -> int:
        stmt = select(func.count()).select_from(ToolDefinition).where(
            ToolDefinition.org_id == org_id, ToolDefinition.deleted_at.is_(None)
        )
        if enabled is not None:
            stmt = stmt.where(ToolDefinition.enabled.is_(enabled))
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_for_org_all(self) -> list[ToolDefinition]:
        """全 org 非软删工具（启动同步 DB→registry 用）。"""
        stmt = select(ToolDefinition).where(ToolDefinition.deleted_at.is_(None))
        return list((await self.session.execute(stmt)).scalars())

    async def search(self, org_id: uuid.UUID, q: str, *, limit: int = 20) -> list[ToolDefinition]:
        """工具发现（REST 版 G3）：name/description ILIKE，org 隔离。"""
        pattern = f"%{q}%"
        stmt = (
            select(ToolDefinition)
            .where(
                ToolDefinition.org_id == org_id,
                ToolDefinition.deleted_at.is_(None),
                (ToolDefinition.name.ilike(pattern)) | (ToolDefinition.description.ilike(pattern)),
            )
            .order_by(ToolDefinition.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def create(
        self,
        *,
        org_id: uuid.UUID,
        name: str,
        description: str,
        params_schema: dict[str, Any],
        tool_type: str,
        enabled: bool = False,
        require_confirm: bool = False,
        idempotent: bool = False,
        sandbox: str = "none",
        allowlist: list[str] | None = None,
        timeout_ms: int = 30000,
        max_concurrency: int = 1,
        mcp_source: str | None = None,
    ) -> ToolDefinition:
        tool = ToolDefinition(
            org_id=org_id,
            name=name,
            description=description,
            params_schema=params_schema,
            tool_type=tool_type,
            enabled=enabled,
            require_confirm=require_confirm,
            idempotent=idempotent,
            sandbox=sandbox,
            allowlist=allowlist,
            timeout_ms=timeout_ms,
            max_concurrency=max_concurrency,
            mcp_source=mcp_source,
            version=1,
        )
        self.session.add(tool)
        return tool

    async def soft_delete(self, tool: ToolDefinition) -> None:
        from datetime import UTC, datetime

        tool.deleted_at = datetime.now(UTC)
        self.session.add(tool)
