"""工作区数据访问（M7-B，docs 04 §3.11）。org 隔离 + 软删过滤。"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.workspace import Workspace


class WorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, workspace_id: uuid.UUID) -> Workspace | None:
        return await self.session.get(Workspace, workspace_id)

    async def get_by_org_name(self, org_id: uuid.UUID, name: str) -> Workspace | None:
        stmt = select(Workspace).where(
            Workspace.org_id == org_id,
            Workspace.name == name,
            Workspace.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def name_exists(self, org_id: uuid.UUID, name: str) -> bool:
        stmt = select(Workspace.id).where(
            Workspace.org_id == org_id,
            Workspace.name == name,
            Workspace.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).first() is not None

    async def list_for_org(
        self, org_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Workspace]:
        stmt = (
            select(Workspace)
            .where(Workspace.org_id == org_id, Workspace.deleted_at.is_(None))
            .order_by(Workspace.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def count_for_org(self, org_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Workspace).where(
            Workspace.org_id == org_id, Workspace.deleted_at.is_(None)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def create(
        self,
        *,
        org_id: uuid.UUID,
        name: str,
        description: str,
        root_path: str,
        system_prompt_fragment: str = "",
        created_by: uuid.UUID | None = None,
    ) -> Workspace:
        ws = Workspace(
            org_id=org_id,
            name=name,
            description=description,
            root_path=root_path,
            system_prompt_fragment=system_prompt_fragment,
            status="active",
            created_by=created_by,
        )
        self.session.add(ws)
        return ws

    async def soft_delete(self, ws: Workspace) -> None:
        from datetime import UTC, datetime

        ws.deleted_at = datetime.now(UTC)
        self.session.add(ws)
