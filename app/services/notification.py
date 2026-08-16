"""通知领域服务（docs 03 §5.11）。落库 + 按 user_id 进程内 SSE 广播（镜像 task.py live-tail）。

产生源：任务事件（set_done/set_failed）+ demo_notify 工具确认执行后。
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_NOTIFICATION_NOT_FOUND, AppError
from app.services.serializers import serialize_notification
from app.storage.models.notification import Notification
from app.storage.repositories.notification import NotificationRepository

# 进程内订阅表（单进程接缝，多实例为 M4 Redis 广播）
_notif_tails: dict[str, list[asyncio.Queue]] = {}


def push_notification(user_id: str, notif: dict[str, Any]) -> None:
    """推通知给该用户全部订阅者（SSE 帧 payload）。"""
    queues = _notif_tails.get(user_id)
    if queues:
        for q in queues:
            q.put_nowait(("notification", notif))


def subscribe_notifications(user_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _notif_tails.setdefault(user_id, []).append(q)
    return q


def unsubscribe_notifications(user_id: str, q: asyncio.Queue) -> None:
    queues = _notif_tails.get(user_id)
    if queues and q in queues:
        queues.remove(q)
        if not queues:
            _notif_tails.pop(user_id, None)


class NotificationService:
    async def create(
        self, db: AsyncSession, user_id: uuid.UUID, title: str, body: str | None = None, level: str = "info"
    ) -> Notification:
        """落库 + commit 后 SSE 广播（先落库再推，防通知先于落库到达）。"""
        row = await NotificationRepository(db).create(user_id=user_id, title=title, body=body, level=level)
        await db.commit()
        await db.refresh(row)
        push_notification(str(user_id), serialize_notification(row))
        return row

    async def list_paged(self, db: AsyncSession, user_id: uuid.UUID, page: int, page_size: int) -> dict[str, Any]:
        repo = NotificationRepository(db)
        items, total = await repo.list_paged(user_id, limit=page_size, offset=(page - 1) * page_size)
        from app.api.schemas.common import paged

        return paged([serialize_notification(n) for n in items], total, page, page_size)

    async def mark_read(self, db: AsyncSession, user: Any, notification_id: uuid.UUID) -> Notification:
        row = await NotificationRepository(db).get_owned(user.id, notification_id)
        if row is None:
            raise AppError(ERR_NOTIFICATION_NOT_FOUND, "通知不存在或无权访问")
        row.read = True
        await db.commit()
        await db.refresh(row)
        return row

async def maybe_notify_from_tool_results(db: AsyncSession, user_id: uuid.UUID, final_state: dict[str, Any]) -> None:
    """demo_notify 确认执行后落一条通知（确认后工具结果 status=done）。"""
    for r in final_state.get("tool_results") or []:
        if r.get("tool_name") == "tl_demo_notify" and r.get("status") == "done":
            await NotificationService().create(
                db,
                user_id=user_id,
                title="通知已送达",
                body=str((r.get("input") or {}).get("message", "") or "工具已执行"),
                level="success",
            )
