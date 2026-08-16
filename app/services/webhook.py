"""Webhook 领域服务（docs 03 §5.10 OC6）：注册/列表/注销 + 外部事件接收。

接收路径（公开，x-hook-token 鉴权非 JWT）：校验 token_hash → x-idempotency-key Redis 去重 →
emit_event 入队（绑定 conversation_id 则投递该线程；否则 org 级收件箱）→ route 安全点消费。
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_HOOK_TOKEN, ERR_TOOL_NOT_FOUND, AppError
from app.services.events import emit_event
from app.storage.models.user import User
from app.storage.models.webhook import WebhookConfig
from app.storage.redis import idem_get, idem_set
from app.storage.repositories.webhook import WebhookRepository
from app.tools.registry import ToolType, get

_IDEM_TTL_S = 3600


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _serialize(h: WebhookConfig) -> dict[str, Any]:
    return {
        "id": str(h.id),
        "tool_id": h.tool_id,
        "conversation_id": str(h.conversation_id) if h.conversation_id else None,
        "enabled": h.enabled,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    }


class WebhookService:
    async def register(
        self, db: AsyncSession, user: User, tool_id: str, token: str, conversation_id: uuid.UUID | None = None
    ) -> WebhookConfig:
        """注册外部回调到事件型工具（docs 03 §5.10）：校验 tool 存在且 tool_type=event，token 只存 hash。"""
        spec = get(tool_id)
        if spec is None:
            raise AppError(ERR_TOOL_NOT_FOUND, "工具不存在")
        if spec.tool_type != ToolType.EVENT:
            raise AppError(40002, f"工具 {tool_id} 不是事件型工具（tool_type=event 才能注册 webhook）")
        repo = WebhookRepository(db)
        existing = await repo.get_by_org_tool(user.org_id, tool_id)
        if existing is not None:
            existing.token_hash = _token_hash(token)
            existing.conversation_id = conversation_id
            existing.enabled = True
            row = existing
        else:
            row = await repo.create(
                org_id=user.org_id, tool_id=tool_id, conversation_id=conversation_id, token_hash=_token_hash(token)
            )
        await db.commit()
        await db.refresh(row)
        return row

    async def list(self, db: AsyncSession, user: User) -> list[dict[str, Any]]:
        return [_serialize(h) for h in await WebhookRepository(db).list_for_org(user.org_id)]

    async def unregister(self, db: AsyncSession, user: User, tool_id: str) -> None:
        repo = WebhookRepository(db)
        row = await repo.get_by_org_tool(user.org_id, tool_id)
        if row is None:
            raise AppError(ERR_TOOL_NOT_FOUND, "Webhook 不存在或无权访问")
        row.deleted_at = datetime.now(UTC)
        await db.commit()

    async def receive(
        self, db: AsyncSession, tool_id: str, token: str, idempotency_key: str | None, payload: dict[str, Any]
    ) -> bool:
        """外部事件接收（公开）：校验 token + 幂等去重 → 入队事件（安全点消费）。

        返回是否处理（True=新事件已入队；False=幂等重复被去重）。未注册/停用 → 404；token 不匹配 → 401。
        """
        row = await WebhookRepository(db).get_by_tool(tool_id)
        if row is None or not row.enabled:
            raise AppError(ERR_TOOL_NOT_FOUND, "Webhook 未注册或已停用")
        if _token_hash(token) != row.token_hash:
            raise AppError(ERR_HOOK_TOKEN, "x-hook-token 不匹配")

        if idempotency_key:
            dedup = f"hook:{row.id}:{idempotency_key}"
            if await idem_get(dedup) is not None:
                return False  # 幂等：重复事件已处理
            await idem_set(dedup, "1", ttl=_IDEM_TTL_S)

        thread_key = str(row.conversation_id) if row.conversation_id else f"org:{row.org_id}"
        emit_event(
            thread_key,
            {
                "type": "webhook",
                "tool_id": tool_id,
                "payload": payload,
                "priority": "urgent" if (payload or {}).get("urgent") else "regular",
            },
        )
        return True
