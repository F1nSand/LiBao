"""MCP 源连接配置实体（docs 01 §7.2 / docs 04 §3.5 补充）。

tool_definition.mcp_source 存 "mcp:{server_id}" 关联；连接配置（命令/URL/headers）
是启动重建 spec 的唯一依据，故独立成表（org 隔离）。
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class McpServer(BaseModel, Base):
    __tablename__ = "mcp_servers"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    transport: Mapped[str] = mapped_column(String(16), nullable=False)  # stdio | http
    command: Mapped[str | None] = mapped_column(Text, nullable=True)  # stdio 原始命令串
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)  # http 端点
    headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
