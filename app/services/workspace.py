"""工作区领域服务（M7-B，docs 03 §5.14）。root_path 后端托管；本地文件夹随 create 创建。"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import (
    ERR_WORKSPACE_NAME_CONFLICT,
    ERR_WORKSPACE_NOT_FOUND,
    ERR_WORKSPACE_PATH_FORBIDDEN,
    AppError,
)
from app.services.serializers import serialize_workspace
from app.storage.models.user import User
from app.storage.models.workspace import Workspace
from app.storage.repositories.workspace import WorkspaceRepository
from app.tools.filesystem import resolve_workspace_path


def workspace_root(workspace_id: uuid.UUID) -> Path:
    """root_path 托管：{workspaces_root}/{workspace_id}（单一来源，防越权）。绝对路径（resolve），
    避免下游 relative_to/路径校验在相对与绝对之间混用。"""
    return (Path(get_settings().workspaces_root) / str(workspace_id)).resolve()


class WorkspaceService:
    async def list_for_org(self, db: AsyncSession, org_id: uuid.UUID, page: int, page_size: int) -> dict[str, Any]:
        repo = WorkspaceRepository(db)
        items = await repo.list_for_org(org_id, limit=page_size, offset=(page - 1) * page_size)
        total = await repo.count_for_org(org_id)
        from app.api.schemas.common import paged

        return paged([serialize_workspace(w) for w in items], total, page, page_size)

    async def get_in_org(self, db: AsyncSession, org_id: uuid.UUID, workspace_id: str) -> Workspace:
        """按 id 或 name 解析；org 隔离。"""
        repo = WorkspaceRepository(db)
        row: Workspace | None = None
        try:
            row = await repo.get_by_id(uuid.UUID(workspace_id))
        except ValueError:
            row = None
        if row is None or row.org_id != org_id or row.deleted_at is not None:
            row = await repo.get_by_org_name(org_id, workspace_id)
        if row is None:
            raise AppError(ERR_WORKSPACE_NOT_FOUND, "工作区不存在或无权访问")
        return row

    async def create(self, db: AsyncSession, user: User, req: Any) -> Workspace:
        repo = WorkspaceRepository(db)
        if await repo.name_exists(user.org_id, req.name):
            raise AppError(ERR_WORKSPACE_NAME_CONFLICT, "同组织下已存在同名工作区")
        row = await repo.create(
            org_id=user.org_id,
            name=req.name,
            description=req.description or "",
            root_path="",  # 先占位，flush 拿到 id 后派生 root_path
            system_prompt_fragment=req.system_prompt_fragment or "",
            created_by=user.id,
        )
        await db.flush()
        root = workspace_root(row.id)
        root.mkdir(parents=True, exist_ok=True)  # 建真实本地文件夹
        row.root_path = str(root)
        await db.commit()
        await db.refresh(row)
        return row

    async def update(self, db: AsyncSession, user: User, workspace_id: str, req: Any) -> Workspace:
        repo = WorkspaceRepository(db)
        row = await self.get_in_org(db, user.org_id, workspace_id)
        if req.name is not None and req.name != row.name:
            if await repo.name_exists(user.org_id, req.name):
                raise AppError(ERR_WORKSPACE_NAME_CONFLICT, "同组织下已存在同名工作区")
            row.name = req.name
        if req.description is not None:
            row.description = req.description
        if req.system_prompt_fragment is not None:
            row.system_prompt_fragment = req.system_prompt_fragment
        await db.commit()
        await db.refresh(row)
        return row

    async def soft_delete(self, db: AsyncSession, user: User, workspace_id: str) -> None:
        row = await self.get_in_org(db, user.org_id, workspace_id)
        await WorkspaceRepository(db).soft_delete(row)
        await db.commit()
        # 本地目录保留（防误删）；归档清理另做

    # ---- 文件（资源管理器，docs 03 §5.14）----

    async def list_files(self, db: AsyncSession, user: User, workspace_id: str, path: str) -> list[dict[str, Any]]:
        ws = await self.get_in_org(db, user.org_id, workspace_id)
        root = Path(ws.root_path)
        target = resolve_workspace_path(root, path or "")
        if not target.is_dir():
            raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "路径不是目录")
        entries: list[dict[str, Any]] = []
        for p in sorted(target.iterdir()):
            entries.append(
                {
                    "name": p.name,
                    "path": str(p.relative_to(root)),
                    "is_dir": p.is_dir(),
                    "size": p.stat().st_size if p.is_file() else 0,
                }
            )
        return entries

    async def read_file_content(self, db: AsyncSession, user: User, workspace_id: str, path: str) -> dict[str, Any]:
        ws = await self.get_in_org(db, user.org_id, workspace_id)
        target = resolve_workspace_path(ws.root_path, path)
        if not target.is_file():
            raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "文件不存在")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = target.read_bytes().decode("utf-8", errors="replace")
        return {"path": path, "content": content[:50000]}

    async def write_file(
        self, db: AsyncSession, user: User, workspace_id: str, path: str, content: str
    ) -> dict[str, Any]:
        ws = await self.get_in_org(db, user.org_id, workspace_id)
        target = resolve_workspace_path(ws.root_path, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content[:100000], encoding="utf-8")
        return {"path": path, "written": min(len(content), 100000)}

    async def delete_file(self, db: AsyncSession, user: User, workspace_id: str, path: str) -> None:
        ws = await self.get_in_org(db, user.org_id, workspace_id)
        target = resolve_workspace_path(ws.root_path, path)
        if target.is_dir():
            raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "目录删除暂不支持（防误删）")
        if target.is_file():
            target.unlink()
