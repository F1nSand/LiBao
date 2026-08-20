"""Skill 实体（M7-A，docs 01 §4.2.1 / docs 04 §3.11）。

org 级 skill = SKILL.md（name + description 路由描述 + body 正文）。默认 enabled=false（约束优先）。
主 agent 自动使用 org 内 enabled skills：路由描述进 system_prompt 前缀，正文经 tl_load_skill 按需取回。
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class Skill(BaseModel, Base):
    __tablename__ = "skills"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)  # manual/git
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
