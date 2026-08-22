"""会话数据访问（docs 04 §3.2）。所有读取默认软删过滤；越权访问由 get_owned 拦截。

文件化：.agent/conversations.json（FileTable，内存过滤/排序/分页等价原 SQL 语义）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.storage.file.store import get_store
from app.storage.models.conversation import Conversation


class ConversationRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.table = get_store().table("conversations")

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
        workspace_id: uuid.UUID | None = None,
    ) -> list[Conversation]:
        # M7-B：workspace_id=None → 只取普通会话（排除工作区会话）；有值 → 只取该工作区会话
        return await self.table.list(
            filter_fn=lambda c: (
                c.user_id == user_id
                and c.deleted_at is None
                and (c.workspace_id is None if workspace_id is None else c.workspace_id == workspace_id)
            ),
            sort_key=lambda c: c.created_at,
            desc=True,
            limit=limit,
            offset=offset,
        )

    async def count_by_user(self, user_id: uuid.UUID, *, workspace_id: uuid.UUID | None = None) -> int:
        return await self.table.count(
            filter_fn=lambda c: (
                c.user_id == user_id
                and c.deleted_at is None
                and (c.workspace_id is None if workspace_id is None else c.workspace_id == workspace_id)
            )
        )

    async def get_owned(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Conversation | None:
        """按 owner 过滤取会话；非本人/已软删返回 None（上层映射 40401）。"""
        row = await self.table.get(conversation_id)
        if row is None or row.deleted_at is not None or row.user_id != user_id:
            return None
        return row

    async def create(
        self, *, user_id: uuid.UUID, agent_id: uuid.UUID, title: str, workspace_id: uuid.UUID | None = None
    ) -> Conversation:
        conv = Conversation(user_id=user_id, agent_id=agent_id, title=title, workspace_id=workspace_id)
        self.table.register(conv)
        return conv

    async def touch_last_message(self, conversation_id: uuid.UUID) -> None:
        """消息落库后刷新 last_message_at（排序用）。"""
        row = await self.table.get(conversation_id)
        if row is not None:
            row.last_message_at = datetime.now(UTC)  # Row.__setattr__ 标脏，commit 落盘

    async def soft_delete(self, conversation: Conversation) -> None:
        conversation.deleted_at = datetime.now(UTC)
