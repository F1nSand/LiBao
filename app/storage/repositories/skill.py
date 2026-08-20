"""Skill 数据访问（M7-A，docs 04 §3.11）。org 隔离 + 软删过滤；enabled 开关。

对齐 tool_definition repo 惯用式（list_for_org/count_for_org/name_exists/soft_delete）。
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.skill import Skill


class SkillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, skill_id: uuid.UUID) -> Skill | None:
        return await self.session.get(Skill, skill_id)

    async def get_by_org_name(self, org_id: uuid.UUID, name: str) -> Skill | None:
        stmt = select(Skill).where(
            Skill.org_id == org_id,
            Skill.name == name,
            Skill.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def name_exists(self, org_id: uuid.UUID, name: str) -> bool:
        stmt = select(Skill.id).where(
            Skill.org_id == org_id,
            Skill.name == name,
            Skill.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).first() is not None

    async def list_for_org(
        self,
        org_id: uuid.UUID,
        *,
        enabled: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Skill]:
        stmt = select(Skill).where(Skill.org_id == org_id, Skill.deleted_at.is_(None))
        if enabled is not None:
            stmt = stmt.where(Skill.enabled.is_(enabled))
        stmt = stmt.order_by(Skill.created_at.desc()).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars())

    async def count_for_org(self, org_id: uuid.UUID, *, enabled: bool | None = None) -> int:
        stmt = select(func.count()).select_from(Skill).where(
            Skill.org_id == org_id, Skill.deleted_at.is_(None)
        )
        if enabled is not None:
            stmt = stmt.where(Skill.enabled.is_(enabled))
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_enabled(self, org_id: uuid.UUID) -> list[Skill]:
        """本组织已启用 skills（主 agent 自动使用，镜像 tools list_enabled_names）。"""
        stmt = (
            select(Skill)
            .where(
                Skill.org_id == org_id,
                Skill.enabled.is_(True),
                Skill.deleted_at.is_(None),
            )
            .order_by(Skill.name)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def create(
        self,
        *,
        org_id: uuid.UUID,
        name: str,
        description: str,
        body: str,
        source: str = "manual",
        enabled: bool = False,
    ) -> Skill:
        skill = Skill(
            org_id=org_id,
            name=name,
            description=description,
            body=body,
            source=source,
            enabled=enabled,
        )
        self.session.add(skill)
        return skill

    async def soft_delete(self, skill: Skill) -> None:
        from datetime import UTC, datetime

        skill.deleted_at = datetime.now(UTC)
        self.session.add(skill)
