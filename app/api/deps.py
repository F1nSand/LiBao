"""API 层依赖注入（docs 01 §2 api/deps.py）。

依赖方向：api → services → storage。get_current_user 不直触存储，经 services/user.py 加载。
服务类 import 延迟到函数体内（避免 storage 就绪前导入失败）；User 模型为纯 SQLAlchemy
（无引擎依赖），顶层 import 安全（routers 已普遍如此），供 require_role 注解被 FastAPI 解析。
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_FORBIDDEN, ERR_INTERNAL, ERR_UNAUTHORIZED, AppError
from app.storage.file.store import FileContext, get_store
from app.storage.models.user import User

_bearer = HTTPBearer(auto_error=False)


async def get_settings_dep() -> object:
    from app.core.config import get_settings

    return get_settings()


async def get_db(request: Request) -> AsyncIterator[FileContext]:
    """请求级文件存储上下文（双轨：文件实体 flush + SQL session 转发，P4 全文件化后简化）。"""
    store = get_store()
    if store is None or store.sql_sessionmaker is None:
        raise AppError(ERR_INTERNAL, "存储未初始化")
    sql = store.sql_sessionmaker()
    ctx = FileContext(store, sql)
    try:
        yield ctx
    finally:
        await sql.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
):
    """校验 JWT 并加载当前用户；失败抛 AppError(40101)，全局处理器返回信封 {code,message,data,trace_id}。"""
    from app.core.security import decode_token
    from app.services.user import UserService

    if credentials is None:
        raise AppError(ERR_UNAUTHORIZED, "未提供认证凭证")
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise AppError(ERR_UNAUTHORIZED, "认证凭证无效或已过期") from None

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise AppError(ERR_UNAUTHORIZED, "认证凭证无效") from None

    service = UserService()
    user = await service.get_by_id(db, user_id)
    if user is None or not user.enabled or user.deleted_at is not None:
        raise AppError(ERR_UNAUTHORIZED, "认证凭证无效或账号已禁用")
    return user


_ROLE_LABELS = {"admin": "管理员", "developer": "开发者", "viewer": "只读用户"}


def require_role(*roles: str):
    """角色守卫依赖工厂（docs 01 §10 RBAC）。

    返回可被 `Depends()` 使用的依赖；校验通过后返回当前 user，故 handler 参数名/类型零改动：
        user: User = Depends(require_admin)
    """
    labels = "/".join(_ROLE_LABELS.get(r, r) for r in roles)

    async def _require_role(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise AppError(ERR_FORBIDDEN, f"需要 {labels} 角色才能访问")
        return user

    return _require_role


require_admin = require_role("admin")                  # 管理员专属
require_developer = require_role("admin", "developer")  # developer+（admin 恒通过）
