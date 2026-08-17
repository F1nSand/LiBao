"""LLM Provider 配置（docs 02 /settings Provider tab，前端契约已对齐）。

api_key 只写不读：API 响应仅 has_key 布尔；明文仅存库（供启动同步到 LLM 客户端），永不回传。
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class ProviderConfig(BaseModel, Base):
    __tablename__ = "provider_configs"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)  # LiteLLM api_base
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)  # LiteLLM model（provider/model 格式）
    api_key: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 明文存库，仅服务端用，不 API 回传
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
