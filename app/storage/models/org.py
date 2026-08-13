"""组织实体（docs 04 §3.1 user/org）。数据隔离维度之一：org_id。"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.base import Base, BaseModel


class Org(BaseModel, Base):
    __tablename__ = "orgs"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
