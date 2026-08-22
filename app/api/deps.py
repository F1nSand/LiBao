"""API 层依赖注入（docs 01 §2 api/deps.py）。

依赖方向：api → services → storage。本地单机化：get_current_user 恒返回固定 admin
（单用户折叠，无 JWT/登录）；get_db 返回文件存储请求上下文（FileContext）。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request

from app.storage.constants import ADMIN_USER
from app.storage.file.store import FileContext, get_store
from app.storage.models.user import User


async def get_settings_dep() -> object:
    from app.core.config import get_settings

    return get_settings()


async def get_db(request: Request) -> AsyncIterator[FileContext]:
    """请求级文件存储上下文（双轨：文件实体 flush + SQL session 转发，P4 全文件化后简化）。"""
    store = get_store()
    if store is None or store.sql_sessionmaker is None:
        raise RuntimeError("存储未初始化")
    async with store.session() as ctx:
        yield ctx


async def get_current_user() -> User:
    """恒返回固定 admin（本地单机单用户；handler 签名零改动）。"""
    return ADMIN_USER


def require_role(*roles: str):
    """角色守卫依赖工厂（折叠：admin 恒在任意角色集合内，恒通过）。

    返回可被 `Depends()` 使用的依赖；校验通过后返回当前 user，故 handler 参数名/类型零改动：
        user: User = Depends(require_admin)
    """

    async def _require_role(user: User = Depends(get_current_user)) -> User:
        return user

    return _require_role


require_admin = require_role("admin")                  # 管理员专属
require_developer = require_role("admin", "developer")  # developer+（admin 恒通过）
