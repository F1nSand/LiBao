"""用户领域服务（docs 01 §5）。登录/鉴权加载用户；deps.get_current_user 依赖此处。"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password
from app.storage.models.user import User
from app.storage.repositories.user import UserRepository


class UserService:
    async def get_by_id(self, db: AsyncSession, user_id: uuid.UUID) -> User | None:
        return await UserRepository(db).get_by_id(user_id)

    async def get_by_username(self, db: AsyncSession, username: str) -> User | None:
        return await UserRepository(db).get_by_username(username)

    async def authenticate(self, db: AsyncSession, username: str, password: str) -> User | None:
        user = await self.get_by_username(db, username)
        if user is None or not verify_password(password, user.password_hash):
            return None
        if not user.enabled:
            return None  # 禁用账号不得登录（与 get_current_user 校验一致）
        return user
