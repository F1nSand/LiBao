"""Webhook 配置（docs 03 §5.10 OC6）。外部事件触发事件型工具的安全入口。

token 只存 hash（不落明文）；conversation_id 绑定事件投递目标线程（可选，空 = org 级收件箱）。
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class WebhookConfig(BaseModel, Base):
    __tablename__ = "webhook_configs"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), index=True, nullable=False
    )
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)  # 事件型工具 registry id（tool_type=event）
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=True  # 事件投递目标线程
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)  # x-hook-token 的 sha256，不落明文
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
