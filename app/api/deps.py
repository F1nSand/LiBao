"""API 层依赖注入（docs 01 §2 api/deps.py）。

依赖方向：api → services → storage。get_current_user 不直触存储，经 services/user.py 加载。
存储相关 import 延迟到函数体内，避免在 storage 就绪前导入失败。
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_UNAUTHORIZED, AppError

_bearer = HTTPBearer(auto_error=False)


async def get_settings_dep() -> object:
    from app.core.config import get_settings

    return get_settings()


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """从 app.state 取全局 async_sessionmaker，逐请求创建会话。"""
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
):
    """校验 JWT 并加载当前用户；失败抛 HTTP 401（detail=错误码数字）。"""
    from app.core.security import decode_token
    from app.services.user import UserService

    if credentials is None:
        raise HTTPException(status_code=401, detail=str(ERR_UNAUTHORIZED))
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail=str(ERR_UNAUTHORIZED)) from None

    service = UserService()
    user = await service.get_by_id(db, uuid.UUID(payload["sub"]))
    if user is None or not getattr(user, "enabled", True) or getattr(user, "deleted_at", None) is not None:
        raise HTTPException(status_code=401, detail=str(ERR_UNAUTHORIZED))
    return user


def ensure_user_in_org(user, org_id: uuid.UUID) -> None:
    """数据隔离：资源必须属于当前用户所在组织（docs 00 多租户隔离）。"""
    if str(user.org_id) != str(org_id):
        raise AppError(40301, "无权访问该资源")
