"""通知数据访问（《02》接口契约 §5.11）。append-only；user 过滤 + 已读标记。文件化：.agent/notifications.json。"""

from __future__ import annotations

import uuid

from app.storage.file.store import get_store
from app.storage.models.notification import Notification


class NotificationRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.table = get_store().table("notifications")

    async def create(
        self, *, user_id: uuid.UUID, title: str, body: str | None = None, level: str = "info"
    ) -> Notification:
        row = Notification(user_id=user_id, title=title, body=body, level=level)
        self.table.register(row)
        return row

    async def list_paged(self, user_id: uuid.UUID, *, limit: int, offset: int) -> tuple[list[Notification], int]:
        rows = await self.table.list(
            filter_fn=lambda n: n.user_id == user_id,
            sort_key=lambda n: n.created_at,
            desc=True,
            limit=limit,
            offset=offset,
        )
        total = await self.table.count(filter_fn=lambda n: n.user_id == user_id)
        return rows, total

    async def get_owned(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification | None:
        row = await self.table.get(notification_id)
        if row is None or row.user_id != user_id:
            return None
        return row
