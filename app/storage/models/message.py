"""消息实体（docs 04 §3.2 message-as-log：消息即日志，DB 列表为权威回放源）。

tool_calls: [{tool_call_id, tool_name, input, output, status, position, duration_ms}]（对齐 mock 形状）
token_usage: {prompt_tokens, completion_tokens, total_tokens, prefix_cache_hit_tokens}
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class Message(BaseModel, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # system/user/assistant/tool
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)  # 该轮推理（reasoning_content，docs 03 §3）
    attachments: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    tool_calls: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    round: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # 轮次（docs 03 §3 逐轮消息扩展）
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
