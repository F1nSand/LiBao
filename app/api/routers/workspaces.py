"""工作区路由（M7-B，docs 03 §5.14）。CRUD（developer+）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_developer
from app.api.envelope import ok
from app.api.schemas.workspace import (
    CreateWorkspaceRequest,
    RenameFileRequest,
    UpdateWorkspaceRequest,
    WriteFileRequest,
)
from app.services.serializers import serialize_workspace
from app.services.workspace import WorkspaceService
from app.storage.models.user import User

router = APIRouter()


@router.get("/workspaces")
async def list_workspaces(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    data = await WorkspaceService().list_for_org(db, user.org_id, page, page_size)
    return ok(data)


@router.post("/workspaces")
async def create_workspace(
    req: CreateWorkspaceRequest,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    row = await WorkspaceService().create(db, user, req)
    return ok(serialize_workspace(row))


@router.get("/workspaces/{workspace_id}")
async def get_workspace(
    workspace_id: str,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    row = await WorkspaceService().get_in_org(db, user.org_id, workspace_id)
    return ok(serialize_workspace(row))


@router.patch("/workspaces/{workspace_id}")
async def update_workspace(
    workspace_id: str,
    req: UpdateWorkspaceRequest,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    row = await WorkspaceService().update(db, user, workspace_id, req)
    return ok(serialize_workspace(row))


@router.delete("/workspaces/{workspace_id}")
async def delete_workspace(
    workspace_id: str,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    await WorkspaceService().hard_delete(db, user, workspace_id)
    return ok()


@router.post("/workspaces/{workspace_id}/reveal")
async def reveal_workspace(
    workspace_id: str,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    """OS 打开工作区本地文件夹（docs 03 §5.14）。存在校验 40416 + developer+。"""
    await WorkspaceService().reveal(db, user, workspace_id)
    return ok()


# ---- 文件（资源管理器，docs 03 §5.14）：读 → 组织成员；写/删 → developer+ ----

@router.get("/workspaces/{workspace_id}/files")
async def list_files(
    workspace_id: str,
    path: str = Query(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await WorkspaceService().list_files(db, user, workspace_id, path))


@router.get("/workspaces/{workspace_id}/files/content")
async def read_file_content(
    workspace_id: str,
    path: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await WorkspaceService().read_file_content(db, user, workspace_id, path))


@router.post("/workspaces/{workspace_id}/files")
async def write_file(
    workspace_id: str,
    req: WriteFileRequest,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    return ok(await WorkspaceService().write_file(db, user, workspace_id, req.path, req.content, req.is_dir))


@router.patch("/workspaces/{workspace_id}/files/rename")
async def rename_file(
    workspace_id: str,
    req: RenameFileRequest,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    """重命名文件/文件夹（目录子项前缀自动同步；docs 03 §5.14）。"""
    await WorkspaceService().rename_file(db, user, workspace_id, req.old_path, req.new_path)
    return ok()


@router.delete("/workspaces/{workspace_id}/files")
async def delete_file(
    workspace_id: str,
    path: str = Query(...),
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    await WorkspaceService().delete_file(db, user, workspace_id, path)
    return ok()
