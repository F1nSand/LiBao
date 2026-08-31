"""消息数据访问（《02》数据模型 §3.2 message-as-log）。列表按 created_at 升序返回，供会话完整回放。

文件化：.agent/sessions/<conversation_id>.jsonl（append-only，追加即落盘）。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.storage.file.store import get_store
from app.storage.models.message import Message


class MessageRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.store = get_store()

    def _rel_path(self, conversation_id: uuid.UUID) -> str:
        return f"sessions/{conversation_id}.jsonl"

    async def list_by_conversation(
        self, conversation_id: uuid.UUID, *, limit: int = 500, offset: int = 0
    ) -> list[Message]:
        # 同 commit 的 created_at 会并列 → round 作次级排序（《02》接口契约 §3 逐轮消息扩展）
        records = await self.store.jsonl_list(self._rel_path(conversation_id))
        rows = [Message.from_dict(r) for r in records if not r.get("deleted_at")]
        rows.sort(key=lambda m: (m.created_at, m.round))
        if offset:
            rows = rows[offset:]
        return rows[:limit] if limit is not None else rows

    async def get_in_conversation(
        self, conversation_id: uuid.UUID, message_id: uuid.UUID
    ) -> Message | None:
        """Return a message only when it belongs to the requested conversation."""
        rows = await self.list_by_conversation(conversation_id, limit=None, offset=0)
        return next((row for row in rows if row.id == message_id), None)

    async def list_active(
        self,
        conversation_id: uuid.UUID,
        head_id: uuid.UUID | None,
        *,
        cursor_initialized: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> list[Message]:
        """Return the active history-parent chain, hiding detached future branches.

        Conversations written before checkpoint support have no cursor; in that case
        this deliberately falls back to the legacy append-only list.
        """
        rows = await self.list_by_conversation(conversation_id, limit=None, offset=0)
        if head_id is None and cursor_initialized:
            return []
        if head_id is None:
            return rows[offset : offset + limit] if limit is not None else rows[offset:]
        by_id = {row.id: row for row in rows}
        chain: list[Message] = []
        current = head_id
        seen: set[uuid.UUID] = set()
        while current in by_id and current not in seen:
            row = by_id[current]
            chain.append(row)
            seen.add(current)
            current = row.history_parent_id
        if not chain:
            if cursor_initialized:
                # An initialized cursor is authoritative. If its head was
                # deleted or belongs to another branch, fail closed instead of
                # resurrecting the append-only history.
                return []
            return rows[offset : offset + limit] if limit is not None else rows[offset:]
        chain.reverse()
        return chain[offset : offset + limit] if limit is not None else chain[offset:]

    async def count(self, conversation_id: uuid.UUID) -> int:
        records = await self.store.jsonl_list(self._rel_path(conversation_id))
        return sum(1 for r in records if not r.get("deleted_at"))

    async def count_active(
        self, conversation_id: uuid.UUID, head_id: uuid.UUID | None, *, cursor_initialized: bool = False
    ) -> int:
        return len(
            await self.list_active(
                conversation_id, head_id, cursor_initialized=cursor_initialized, limit=None, offset=0
            )
        )

    async def create(
        self,
        *,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        thinking: str | None = None,
        attachments: list | None = None,
        file_refs: list | None = None,
        tool_calls: list | None = None,
        token_usage: dict[str, Any] | None = None,
        parent_id: uuid.UUID | None = None,
        trace_id: str | None = None,
        round: int = 1,
        message_id: uuid.UUID | None = None,
        checkpoint_id: uuid.UUID | None = None,
        history_parent_id: uuid.UUID | None = None,
    ) -> Message:
        msg = Message(
            id=message_id or uuid.uuid4(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            thinking=thinking,
            attachments=attachments or [],
            file_refs=file_refs or [],
            tool_calls=tool_calls or [],
            token_usage=token_usage,
            parent_id=parent_id,
            round=round,
            trace_id=trace_id,
            checkpoint_id=checkpoint_id,
            history_parent_id=history_parent_id,
        )
        await self.store.jsonl_append(self._rel_path(conversation_id), msg.to_dict())
        return msg
