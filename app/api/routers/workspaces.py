"""工作区路由（M7-B，docs 03 §5.14）。CRUD（developer+）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_developer
from app.api.envelope import ok
from app.api.schemas.workspace import CreateWorkspaceRequest, UpdateWorkspaceRequest
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
    await WorkspaceService().soft_delete(db, user, workspace_id)
    return ok()
