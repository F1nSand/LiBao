"""会话领域服务（docs 01 §5 services/conversation.py）。owner 过滤 → 越权 40401。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_CONVERSATION_NOT_FOUND, AppError
from app.services.serializers import serialize_conversation, serialize_message, serialize_trajectory_node
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

    async def create(
        self, db: AsyncSession, user: User, agent: AgentConfig, title: str, workspace_id: uuid.UUID | None = None
    ) -> Conversation:
        # 调用方负责解析默认通用 Agent（AgentService.get_default），此处不再重复查询
        conv = await ConversationRepository(db).create(
            user_id=user.id, agent_id=agent.id, title=title, workspace_id=workspace_id
        )
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

    async def trajectory(
        self, db: AsyncSession, conversation: Conversation, before_seq: int | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """只读轨迹（docs 03 §5.2.1）：由 message + tool_calls 派生，非独立存储。

        seq 为按消息序的前端派生索引（非持久化；新消息插入会移位，可接受）。
        before_seq 加载更早一页；has_more 表示还有更早。
        """
        msgs = await MessageRepository(db).list_by_conversation(conversation.id, limit=10000, offset=0)
        nodes = [serialize_trajectory_node(m, seq) for seq, m in enumerate(msgs, 1)]
        candidates = [n for n in nodes if n["seq"] < before_seq] if before_seq is not None else nodes
        return {
            "conversation_id": str(conversation.id),
            "nodes": candidates[-limit:],
            "has_more": len(candidates) > limit,
        }
