"""Webhook 路由（docs 03 §5.10 OC6）。

- `POST /hooks/{tool_id}/register`、`GET /hooks`、`DELETE /hooks/{tool_id}`：JWT 鉴权（管理侧）。
- `POST /hooks/{tool_id}`：公开接收（`x-hook-token` 非 JWT + `x-idempotency-key` 去重）→ 事件入队安全点消费。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.api.envelope import ok
from app.core.errors import ERR_HOOK_TOKEN, AppError
from app.services.webhook import WebhookService
from app.storage.models.user import User

router = APIRouter()


@router.post("/hooks/{tool_id}/register")
async def register_hook(
    tool_id: str,
    token: str = Body(..., embed=True, description="webhook 共享密钥（只存 hash，调用方需保管）"),
    conversation_id: uuid.UUID | None = Body(None, embed=True, description="事件投递目标会话（可选）"),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    row = await WebhookService().register(db, user, tool_id, token, conversation_id)
    return ok({"id": str(row.id), "tool_id": row.tool_id, "conversation_id": row.conversation_id})


@router.get("/hooks")
async def list_hooks(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(await WebhookService().list(db, user))


@router.delete("/hooks/{tool_id}")
async def unregister_hook(
    tool_id: str,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await WebhookService().unregister(db, user, tool_id)
    return ok()


@router.post("/hooks/{tool_id}")
async def receive_hook(
    tool_id: str,
    payload: dict = Body(default_factory=dict),
    x_hook_token: str | None = Header(None, alias="x-hook-token"),
    x_idempotency_key: str | None = Header(None, alias="x-idempotency-key"),
    db: AsyncSession = Depends(get_db),
):
    """公开接收：外部系统触发事件型工具。token 匹配 + 幂等去重 → 事件入队。"""
    if not x_hook_token:
        raise AppError(ERR_HOOK_TOKEN, "缺少 x-hook-token")
    processed = await WebhookService().receive(db, tool_id, x_hook_token, x_idempotency_key, payload)
    return ok({"processed": processed})
