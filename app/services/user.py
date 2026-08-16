"""用户领域服务（docs 01 §5）。登录/鉴权加载用户 + 管理 CRUD（2e）。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_USER_NOT_FOUND, ERR_USERNAME_CONFLICT, AppError
from app.core.security import hash_password, verify_password
from app.services.serializers import serialize_user
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

    # ---- 管理 CRUD（2e，docs 03 §5.1）----

    async def list_paged(self, db: AsyncSession, page: int, page_size: int) -> dict[str, Any]:
        repo = UserRepository(db)
        items, total = await repo.list_paged(limit=page_size, offset=(page - 1) * page_size)
        from app.api.schemas.common import paged

        return paged([serialize_user(u) for u in items], total, page, page_size)

    async def create_user(
        self,
        db: AsyncSession,
        *,
        username: str,
        password: str,
        name: str,
        role: str,
        org_id: uuid.UUID,
    ) -> User:
        repo = UserRepository(db)
        if await repo.get_by_username(username) is not None:
            raise AppError(ERR_USERNAME_CONFLICT, f"用户名 {username} 已存在")
        row = await repo.create(
            username=username, password_hash=hash_password(password), name=name, role=role, org_id=org_id
        )
        await db.commit()
        await db.refresh(row)
        return row

    async def get_owned(self, db: AsyncSession, user_id: uuid.UUID) -> User:
        user = await UserRepository(db).get_by_id(user_id)
        if user is None or user.deleted_at is not None:
            raise AppError(ERR_USER_NOT_FOUND, "用户不存在")
        return user

    async def change_role(self, db: AsyncSession, user_id: uuid.UUID, role: str) -> User:
        user = await self.get_owned(db, user_id)
        await UserRepository(db).update_role(user, role)
        await db.commit()
        await db.refresh(user)
        return user

    async def change_enabled(self, db: AsyncSession, user_id: uuid.UUID, enabled: bool) -> User:
        user = await self.get_owned(db, user_id)
        await UserRepository(db).set_enabled(user, enabled)
        await db.commit()
        await db.refresh(user)
        return user

    async def soft_delete(self, db: AsyncSession, user_id: uuid.UUID) -> None:
        user = await self.get_owned(db, user_id)
        await UserRepository(db).soft_delete(user)
        await db.commit()
