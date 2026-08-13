"""会话数据访问（docs 04 §3.2）。所有读取默认软删过滤；越权访问由 get_owned 拦截。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.conversation import Conversation


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_user(
        self, user_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.deleted_at.is_(None))
            .order_by(Conversation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def count_by_user(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.user_id == user_id, Conversation.deleted_at.is_(None))
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def get_owned(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Conversation | None:
        """按 owner 过滤取会话；非本人/已软删返回 None（上层映射 40401）。"""
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, *, user_id: uuid.UUID, agent_id: uuid.UUID, title: str) -> Conversation:
        conv = Conversation(user_id=user_id, agent_id=agent_id, title=title)
        self.session.add(conv)
        return conv

    async def touch_last_message(self, conversation_id: uuid.UUID) -> None:
        """消息落库后刷新 last_message_at（排序用）。"""
        await self.session.execute(
            Conversation.__table__.update()
            .where(Conversation.id == conversation_id)
            .values(last_message_at=datetime.now(UTC))
        )

    async def soft_delete(self, conversation: Conversation) -> None:
        conversation.deleted_at = datetime.now(UTC)
        self.session.add(conversation)
