"""认证路由（docs 03 §5.1）。登录失败返回 HTTP 200 + code 40101（对齐 mock）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.envelope import fail, ok
from app.api.schemas.auth import LoginRequest
from app.core.errors import ERR_UNAUTHORIZED
from app.core.security import create_access_token
from app.services.serializers import serialize_user
from app.services.user import UserService
from app.storage.models.user import User

router = APIRouter()


@router.post("/auth/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await UserService().authenticate(db, req.username, req.password)
    if user is None:
        return fail(ERR_UNAUTHORIZED, "用户名或密码错误")
    org_name = await UserService().get_org_name(db, user.org_id)
    return ok({"token": create_access_token(user), "user": serialize_user(user, org_name=org_name)})


@router.get("/auth/me")
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_name = await UserService().get_org_name(db, user.org_id)
    return ok(serialize_user(user, org_name=org_name))


@router.post("/auth/logout")
async def logout(user: User = Depends(get_current_user)):
    return ok()
