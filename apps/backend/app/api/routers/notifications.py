"""通知路由（《02》接口契约 §5.11）。分页列表 / 已读 / SSE 实时流（按 user_id）。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.core.events import sse_emitter
from app.services.notification import NotificationService, subscribe_notifications, unsubscribe_notifications
from app.services.serializers import serialize_notification
from app.storage.models.user import User

router = APIRouter()

_KEEPALIVE = 15


@router.get("/notifications")
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    return ok(await NotificationService().list_paged(db, user.id, page, page_size))


@router.patch("/notifications/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Any = Depends(get_db),
):
    return ok(serialize_notification(await NotificationService().mark_read(db, user, notification_id)))


@router.get("/notifications/stream")
async def notification_stream(
    user: User = Depends(get_current_user),
):
    """SSE 实时通知（按 user_id 订阅，镜像 task live-tail；前端 useSSE 直连）。"""
    emit = sse_emitter()
    q = await subscribe_notifications(str(user.id))

    async def gen():
        try:
            while True:
                try:
                    event_type, payload = await asyncio.wait_for(q.get(), timeout=_KEEPALIVE)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if event_type == "notification":
                    yield emit("notification", payload)
        finally:
            await unsubscribe_notifications(str(user.id), q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
