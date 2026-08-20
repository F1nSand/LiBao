"""工作区实体（M7-B，docs 04 §3.11）。

工作区 = 本地文件夹（root_path）+ 项目级 agent 增量（system_prompt_fragment）+ 独立记忆 + 项目 skills/工具。
org 级共享；root_path 由后端托管（{workspaces_root}/{id}），用户不指定磁盘路径（防越权）。
"""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class Workspace(BaseModel, Base):
    __tablename__ = "workspaces"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    root_path: Mapped[str] = mapped_column(String(512), nullable=False)
    system_prompt_fragment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active/archived
    # 创建者（审计元数据；无 FK，避免级联/清理顺序耦合）
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
