"""用户管理路由（docs 03 §5.1，admin 专属）。零建表（复用 User 现有字段）。"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
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


def _require_admin(user: User) -> None:
    """admin 守卫（M6 完整 RBAC 前的最简实现）。"""
    if user.role != "admin":
        raise AppError(ERR_FORBIDDEN, "仅管理员可执行用户管理")


@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    return ok(await UserService().list_paged(db, page, page_size))


@router.post("/users")
async def create_user(
    req: CreateUserRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    created = await UserService().create_user(
        db,
        username=req.username,
        password=req.password,
        name=req.name,
        role=req.role,
        org_id=req.org_id or user.org_id,  # 未指定 org 归入当前管理员组织
    )
    return ok(serialize_user(created))


@router.patch("/users/{user_id}/role")
async def patch_user_role(
    user_id: uuid.UUID,
    req: RoleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    return ok(serialize_user(await UserService().change_role(db, user_id, req.role)))


@router.patch("/users/{user_id}/status")
async def patch_user_status(
    user_id: uuid.UUID,
    req: StatusRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    return ok(serialize_user(await UserService().change_enabled(db, user_id, req.enabled)))


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_admin(user)
    await UserService().soft_delete(db, user_id)
    return ok()
