"""用户数据访问（docs 01 §2 storage/repositories）。登录/鉴权 + 管理 CRUD（2e）。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username, User.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ---- 管理 CRUD（2e，docs 03 §5.1）----

    async def create(self, *, username: str, password_hash: str, name: str, role: str, org_id: uuid.UUID) -> User:
        row = User(username=username, password_hash=password_hash, name=name, role=role, org_id=org_id)
        self.session.add(row)
        return row

    async def list_paged(self, *, limit: int, offset: int) -> tuple[list[User], int]:
        base = select(User).where(User.deleted_at.is_(None))
        total = int((await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
        stmt = base.order_by(User.created_at.desc()).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars()), total

    async def update_role(self, user: User, role: str) -> None:
        user.role = role

    async def set_enabled(self, user: User, enabled: bool) -> None:
        user.enabled = enabled

    async def soft_delete(self, user: User) -> None:
        user.deleted_at = datetime.now(UTC)
