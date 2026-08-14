"""会话领域服务（docs 01 §5 services/conversation.py）。owner 过滤 → 越权 40401。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_CONVERSATION_NOT_FOUND, AppError
from app.services.serializers import serialize_conversation, serialize_message
from app.storage.models.agent import AgentConfig
from app.storage.models.conversation import Conversation
from app.storage.models.user import User
from app.storage.repositories.conversation import ConversationRepository
from app.storage.repositories.message import MessageRepository


class ConversationService:
    async def list(self, db: AsyncSession, user_id: uuid.UUID, page: int, page_size: int) -> dict[str, Any]:
        repo = ConversationRepository(db)
        items = await repo.list_by_user(user_id, limit=page_size, offset=(page - 1) * page_size)
        total = await repo.count_by_user(user_id)
        from app.api.schemas.common import paged

        return paged([serialize_conversation(c) for c in items], total, page, page_size)

    async def create(self, db: AsyncSession, user: User, agent: AgentConfig, title: str) -> Conversation:
        # 调用方负责校验 agent（published + 同 org，AgentService.get_published），此处不再重复查询
        conv = await ConversationRepository(db).create(user_id=user.id, agent_id=agent.id, title=title)
        await db.commit()
        await db.refresh(conv)
        return conv

    async def get_owned(self, db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Conversation:
        conv = await ConversationRepository(db).get_owned(conversation_id, user_id)
        if conv is None:
            raise AppError(ERR_CONVERSATION_NOT_FOUND, "会话不存在或无权访问")
        return conv

    async def delete(self, db: AsyncSession, conversation: Conversation) -> None:
        await ConversationRepository(db).soft_delete(conversation)
        await db.commit()

    async def messages(
        self, db: AsyncSession, conversation: Conversation, page: int, page_size: int
    ) -> dict[str, Any]:
        repo = MessageRepository(db)
        msgs = await repo.list_by_conversation(conversation.id, limit=page_size, offset=(page - 1) * page_size)
        total = await repo.count(conversation.id)
        from app.api.schemas.common import paged

        return paged([serialize_message(m) for m in msgs], total, page, page_size)
