"""通知数据访问（docs 03 §5.11）。append-only；user 过滤 + 已读标记。"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.notification import Notification


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, *, user_id: uuid.UUID, title: str, body: str | None = None, level: str = "info"
    ) -> Notification:
        row = Notification(user_id=user_id, title=title, body=body, level=level)
        self.session.add(row)
        return row

    async def list_paged(self, user_id: uuid.UUID, *, limit: int, offset: int) -> tuple[list[Notification], int]:
        base = select(Notification).where(Notification.user_id == user_id)
        total = int(
            (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        )
        stmt = base.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
        items = list((await self.session.execute(stmt)).scalars())
        return items, total

    async def get_owned(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification | None:
        stmt = select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()
