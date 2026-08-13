"""工具定义实体（docs 04 §3.5）。

内置工具与 MCP 注册的工具同走 tool_definition 生命周期；enabled 默认关闭（约束优先）。
sandbox: none / docker / microvm；tool_type: perception / execution / collaboration / user_comms / event。
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class ToolDefinition(BaseModel, Base):
    __tablename__ = "tool_definitions"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    params_schema: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    tool_type: Mapped[str] = mapped_column(String(32), default="execution", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_confirm: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idempotent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sandbox: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    allowlist: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=30000, nullable=False)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    mcp_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
