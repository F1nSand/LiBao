"""运行日志实体（docs 04 §3.10）。全链路 append-only，trace_id 贯穿；M5 演进为 span 树。

type: llm / tool / retrieval / memory / node / custom；status: ok / error / retried。
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class RunLog(BaseModel, Base):
    __tablename__ = "run_logs"

    trace_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True
    )
    node: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    type: Mapped[str] = mapped_column(String(16), default="node", nullable=False)
    input: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    output: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
