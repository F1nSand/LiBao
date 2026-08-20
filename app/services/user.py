"""用户领域服务（docs 01 §5）。登录/鉴权加载用户 + 管理 CRUD（2e）。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_FORBIDDEN, ERR_USER_NOT_FOUND, ERR_USERNAME_CONFLICT, AppError
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

    async def list_paged(
        self, db: AsyncSession, page: int, page_size: int, org_id: uuid.UUID | None = None
    ) -> dict[str, Any]:
        repo = UserRepository(db)
        items, total = await repo.list_paged(limit=page_size, offset=(page - 1) * page_size, org_id=org_id)
        org_names = await self._org_names(db, items)
        from app.api.schemas.common import paged

        return paged([serialize_user(u, org_name=org_names.get(u.org_id)) for u in items], total, page, page_size)

    async def get_org_name(self, db: AsyncSession, org_id: uuid.UUID) -> str | None:
        """查 org 名称（serialize_user 补 org_name 用）。"""
        from sqlalchemy import select

        from app.storage.models.org import Org

        return (await db.execute(select(Org.name).where(Org.id == org_id))).scalar_one_or_none()

    async def _org_names(self, db: AsyncSession, users: list[User]) -> dict[uuid.UUID, str]:
        """批量查 org 名称（list_paged 一条 IN 查询，避免逐用户 N+1）。"""
        org_ids = {u.org_id for u in users}
        if not org_ids:
            return {}
        from sqlalchemy import select

        from app.storage.models.org import Org

        rows = (await db.execute(select(Org.id, Org.name).where(Org.id.in_(org_ids)))).all()
        return {oid: name for oid, name in rows}

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

    @staticmethod
    def _guard_self(user: User, user_id: uuid.UUID) -> None:
        """禁止对自身执行角色/启停/删除（否则最后一个 admin 可自删/自禁 → org 自锁死）。"""
        if user_id == user.id:
            raise AppError(ERR_FORBIDDEN, "不能对自己执行此管理操作")

    async def get_owned(self, db: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID) -> User:
        """取本组织用户（org admin 只能改本组织用户；跨 org 一律视为不存在，防存在性探测）。"""
        user = await UserRepository(db).get_by_id(user_id)
        if user is None or user.deleted_at is not None or user.org_id != org_id:
            raise AppError(ERR_USER_NOT_FOUND, "用户不存在")
        return user

    async def change_role(self, db: AsyncSession, user: User, user_id: uuid.UUID, role: str) -> User:
        self._guard_self(user, user_id)
        target = await self.get_owned(db, user_id, user.org_id)
        await UserRepository(db).update_role(target, role)
        await db.commit()
        await db.refresh(target)
        return target

    async def change_enabled(self, db: AsyncSession, user: User, user_id: uuid.UUID, enabled: bool) -> User:
        self._guard_self(user, user_id)
        target = await self.get_owned(db, user_id, user.org_id)
        await UserRepository(db).set_enabled(target, enabled)
        await db.commit()
        await db.refresh(target)
        return target

    async def soft_delete(self, db: AsyncSession, user: User, user_id: uuid.UUID) -> None:
        self._guard_self(user, user_id)
        target = await self.get_owned(db, user_id, user.org_id)
        await UserRepository(db).soft_delete(target)
        await db.commit()
