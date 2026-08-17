"""消息数据访问（docs 04 §3.2 message-as-log）。列表按 created_at 升序返回，供会话完整回放。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.message import Message


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_conversation(
        self, conversation_id: uuid.UUID, *, limit: int = 500, offset: int = 0
    ) -> list[Message]:
        # 同 commit 的 created_at 会并列 → round 作次级排序（docs 03 §3 逐轮消息扩展）
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.deleted_at.is_(None))
            .order_by(Message.created_at.asc(), Message.round.asc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def count(self, conversation_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(Message).where(
            Message.conversation_id == conversation_id, Message.deleted_at.is_(None)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def create(
        self,
        *,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        thinking: str | None = None,
        attachments: list | None = None,
        tool_calls: list | None = None,
        token_usage: dict[str, Any] | None = None,
        parent_id: uuid.UUID | None = None,
        trace_id: str | None = None,
        round: int = 1,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            thinking=thinking,
            attachments=attachments or [],
            tool_calls=tool_calls or [],
            token_usage=token_usage,
            parent_id=parent_id,
            round=round,
            trace_id=trace_id,
        )
        self.session.add(msg)
        return msg
