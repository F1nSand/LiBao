"""记忆实体（docs 04 §3.8）。三层记忆：轨迹（append-only）+ 长期记忆（版本化只增）+ 业务状态（不入此表）。

只增原则（ADR-06）：改写 = 新增 version 行 + 更新卡片 current_version；删除 = 软删；历史永远保留。
memory_trace / longterm_memory_version 不继承 BaseModel 的 deleted_at（物理上强制 append-only）。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class MemoryTrace(Base):
    """对话轨迹（append-only，无软删列）。maintenance 的原料；由 chat_stream 落库。"""

    __tablename__ = "memory_trace"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # system/user/assistant/tool
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LongTermMemory(BaseModel, Base):
    """长期记忆卡片（软删）。content 恒为 dict：json_card 存结构化数据，note 存 {"text": str}。"""

    __tablename__ = "longterm_memory"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False)
    card_type: Mapped[str] = mapped_column(String(16), nullable=False)  # json_card | note
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    importance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 0-1
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)  # manual | maintenance
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LongTermMemoryVersion(Base):
    """长期记忆版本（append-only，UNIQUE(memory_id, version)）。"""

    __tablename__ = "longterm_memory_version"
    __table_args__ = (UniqueConstraint("memory_id", "version", name="uniq_longterm_memory_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("longterm_memory.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    importance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
