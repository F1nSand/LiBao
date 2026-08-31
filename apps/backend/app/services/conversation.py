"""会话领域服务（《02》后端设计 §5 services/conversation.py）。owner 过滤 → 越权 40401。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.core.errors import ERR_CONVERSATION_NOT_FOUND, AppError
from app.core.session_cache import remove_session_workspace
from app.services.serializers import serialize_conversation, serialize_message, serialize_trajectory_node
from app.storage.models.agent import AgentConfig
from app.storage.models.conversation import Conversation
from app.storage.models.user import User
from app.storage.repositories.conversation import ConversationRepository
from app.storage.repositories.message import MessageRepository


class ConversationService:
    @staticmethod
    async def _ensure_message_cursor_initialized(db: Any, conversation: Conversation) -> None:
        """Lazily mark legacy conversations with a known head as branch-aware."""
        if not conversation.message_cursor_initialized and conversation.active_message_head_id is not None:
            conversation.message_cursor_initialized = True
            await db.commit()

    async def list(
        self,
        db: Any,
        user_id: uuid.UUID,
        page: int,
        page_size: int,
        workspace_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        repo = ConversationRepository(db)
        items = await repo.list_by_user(
            user_id, limit=page_size, offset=(page - 1) * page_size, workspace_id=workspace_id
        )
        total = await repo.count_by_user(user_id, workspace_id=workspace_id)
        from app.api.schemas.common import paged

        return paged([serialize_conversation(c) for c in items], total, page, page_size)

    async def create(
        self, db: Any, user: User, agent: AgentConfig, title: str, workspace_id: uuid.UUID | None = None
    ) -> Conversation:
        # 调用方负责解析默认通用 Agent（AgentService.get_default），此处不再重复查询
        conv = await ConversationRepository(db).create(
            user_id=user.id, agent_id=agent.id, title=title, workspace_id=workspace_id
        )
        await db.commit()
        await db.refresh(conv)
        return conv

    async def get_owned(self, db: Any, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Conversation:
        conv = await ConversationRepository(db).get_owned(conversation_id, user_id)
        if conv is None:
            raise AppError(ERR_CONVERSATION_NOT_FOUND, "会话不存在或无权访问")
        return conv

    async def delete(self, db: Any, conversation: Conversation) -> None:
        await ConversationRepository(db).soft_delete(conversation)
        await db.commit()
        # 普通会话使用 cache/sessions/<id>；工作区会话目录属于项目，绝不随会话删除。
        if conversation.workspace_id is None:
            await asyncio.to_thread(remove_session_workspace, conversation.id)

    async def messages(
        self, db: Any, conversation: Conversation, page: int, page_size: int
    ) -> dict[str, Any]:
        await self._ensure_message_cursor_initialized(db, conversation)
        repo = MessageRepository(db)
        msgs = await repo.list_active(
            conversation.id,
            conversation.active_message_head_id,
            cursor_initialized=conversation.message_cursor_initialized,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        total = await repo.count_active(
            conversation.id,
            conversation.active_message_head_id,
            cursor_initialized=conversation.message_cursor_initialized,
        )
        from app.checkpoints.runtime import get_checkpoint_service
        from app.core.config import get_settings

        checkpoint_service = get_checkpoint_service(
            get_settings().agent_data_dir, get_settings().checkpoint_retention_days
        )
        checkpoints = {
            item.id: item for item in await checkpoint_service.store.list_checkpoints(conversation.id)
        }
        serialized = []
        for message in msgs:
            item = serialize_message(message)
            checkpoint = checkpoints.get(getattr(message, "checkpoint_id", None))
            if checkpoint is not None:
                item["checkpoint"] = {
                    "id": str(checkpoint.id),
                    "status": checkpoint.status,
                    "changed_file_count": len(checkpoint.files),
                    "can_restore_code": checkpoint.status in {"open", "sealed", "interrupted"},
                    "can_restore_conversation": (
                        checkpoint.status in {"open", "sealed", "interrupted"}
                        and checkpoint.graph_parent_bound
                    ),
                }
            serialized.append(item)
        from app.api.schemas.common import paged

        return paged(serialized, total, page, page_size)

    async def trajectory(
        self, db: Any, conversation: Conversation, before_seq: int | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """只读轨迹（《02》接口契约 §5.2.1）：由 message + tool_calls 派生，非独立存储。

        seq 为按消息序的前端派生索引（非持久化；新消息插入会移位，可接受）。
        before_seq 加载更早一页；has_more 表示还有更早。
        """
        await self._ensure_message_cursor_initialized(db, conversation)
        msgs = await MessageRepository(db).list_active(
            conversation.id,
            conversation.active_message_head_id,
            cursor_initialized=conversation.message_cursor_initialized,
            limit=10000,
            offset=0,
        )
        nodes = [serialize_trajectory_node(m, seq) for seq, m in enumerate(msgs, 1)]
        candidates = [n for n in nodes if n["seq"] < before_seq] if before_seq is not None else nodes
        return {
            "conversation_id": str(conversation.id),
            "nodes": candidates[-limit:],
            "has_more": len(candidates) > limit,
        }
