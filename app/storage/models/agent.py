"""Agent 配置与其版本快照（docs 04 §3.4）。

agent_version 保存每次发布快照（append-only），prefix_hash 为静态前缀缓存键（docs 01 §4.1）。
graph_template: single / proposer_reviewer / manager_worker（多 Agent 为 M4，M1 只用 single）。
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class AgentConfig(BaseModel, Base):
    __tablename__ = "agent_configs"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    graph_template: Mapped[str] = mapped_column(String(32), default="single", nullable=False)
    skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    tools: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    max_steps: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)  # draft/published/disabled
    current_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AgentVersion(BaseModel, Base):
    __tablename__ = "agent_versions"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_configs.id"), index=True, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    tools: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    prefix_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
