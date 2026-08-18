"""用户管理路由（docs 03 §5.1，admin 专属）。零建表（复用 User 现有字段）。"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.api.envelope import ok
from app.core.errors import ERR_FORBIDDEN, AppError
from app.services.serializers import serialize_user
from app.services.user import UserService
from app.storage.models.user import User

router = APIRouter()

Role = Literal["admin", "developer", "viewer"]


class CreateUserRequest(BaseModel):
    username: str
    password: str
    name: str
    role: Role = "viewer"
    org_id: uuid.UUID | None = None


class RoleRequest(BaseModel):
    role: Role


class StatusRequest(BaseModel):
    enabled: bool


@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(await UserService().list_paged(db, page, page_size, org_id=user.org_id))


@router.post("/users")
async def create_user(
    req: CreateUserRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if req.org_id not in (None, user.org_id):
        raise AppError(ERR_FORBIDDEN, "只能在本组织内创建用户")
    created = await UserService().create_user(
        db,
        username=req.username,
        password=req.password,
        name=req.name,
        role=req.role,
        org_id=user.org_id,  # 统一归入当前管理员组织（跨 org 写入已拒）
    )
    return ok(serialize_user(created))


@router.patch("/users/{user_id}/role")
async def patch_user_role(
    user_id: uuid.UUID,
    req: RoleRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(serialize_user(await UserService().change_role(db, user, user_id, req.role)))


@router.patch("/users/{user_id}/status")
async def patch_user_status(
    user_id: uuid.UUID,
    req: StatusRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(serialize_user(await UserService().change_enabled(db, user, user_id, req.enabled)))


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await UserService().soft_delete(db, user, user_id)
    return ok()
