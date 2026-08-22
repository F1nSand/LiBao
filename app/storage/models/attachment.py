"""附件实体（docs 04 §3.7）。本地磁盘存储 MVP（MinIO 为 M4 接缝）；软删行 + 删磁盘文件。

状态机：uploaded → analyzing → ready | failed（前端 2.5s 轮询 /attachments/{id}/analysis）。
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class Attachment(BaseModel, Base):
    __tablename__ = "attachments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True  # conversations FK 已随文件化移除（列保留）
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)  # {upload_dir}/{attachment_id}
    status: Mapped[str] = mapped_column(
        String(16), default="uploaded", nullable=False
    )  # uploaded/analyzing/ready/failed
    analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
