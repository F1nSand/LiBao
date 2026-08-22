"""工作区数据访问（M7-B，docs 04 §3.11）。软删过滤。文件化：.agent/workspaces.json。"""

from __future__ import annotations

import uuid

from app.storage.file.store import get_store
from app.storage.models.workspace import Workspace


class WorkspaceRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.table = get_store().table("workspaces")

    async def get_by_id(self, workspace_id: uuid.UUID) -> Workspace | None:
        row = await self.table.get(workspace_id)
        if row is None or row.deleted_at is not None:
            return None
        return row

    async def get_by_org_name(self, org_id: uuid.UUID, name: str) -> Workspace | None:
        rows = await self.table.list(
            filter_fn=lambda w: w.name == name and w.deleted_at is None, limit=1
        )
        return rows[0] if rows else None

    async def name_exists(self, org_id: uuid.UUID, name: str) -> bool:
        return await self.get_by_org_name(org_id, name) is not None

    async def list_for_org(
        self, org_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Workspace]:
        return await self.table.list(
            filter_fn=lambda w: w.deleted_at is None,
            sort_key=lambda w: w.created_at,
            desc=True,
            limit=limit,
            offset=offset,
        )

    async def count_for_org(self, org_id: uuid.UUID) -> int:
        return await self.table.count(filter_fn=lambda w: w.deleted_at is None)

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
        self.table.register(ws)
        return ws
