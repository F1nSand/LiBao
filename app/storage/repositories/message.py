"""消息数据访问（docs 04 §3.2 message-as-log）。列表按 created_at 升序返回，供会话完整回放。

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
        # 同 commit 的 created_at 会并列 → round 作次级排序（docs 03 §3 逐轮消息扩展）
        records = await self.store.jsonl_list(self._rel_path(conversation_id))
        rows = [Message.from_dict(r) for r in records if not r.get("deleted_at")]
        rows.sort(key=lambda m: (m.created_at, m.round))
        if offset:
            rows = rows[offset:]
        return rows[:limit] if limit is not None else rows

    async def count(self, conversation_id: uuid.UUID) -> int:
        records = await self.store.jsonl_list(self._rel_path(conversation_id))
        return sum(1 for r in records if not r.get("deleted_at"))

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
        await self.store.jsonl_append(self._rel_path(conversation_id), msg.to_dict())
        return msg
