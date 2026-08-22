"""Skill 数据访问（M7-A，docs 04 §3.11）。软删过滤；enabled 开关。文件化：.agent/skills.json。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.storage.file.store import get_store
from app.storage.models.skill import Skill


class SkillRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.table = get_store().table("skills")

    async def get_by_id(self, skill_id: uuid.UUID) -> Skill | None:
        row = await self.table.get(skill_id)
        if row is None or row.deleted_at is not None:
            return None
        return row

    async def get_by_org_name(self, org_id: uuid.UUID, name: str) -> Skill | None:
        rows = await self.table.list(
            filter_fn=lambda s: s.name == name and s.deleted_at is None, limit=1
        )
        return rows[0] if rows else None

    async def name_exists(self, org_id: uuid.UUID, name: str) -> bool:
        return await self.get_by_org_name(org_id, name) is not None

    async def list_for_org(
        self,
        org_id: uuid.UUID,
        *,
        enabled: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Skill]:
        return await self.table.list(
            filter_fn=lambda s: s.deleted_at is None and (enabled is None or s.enabled == enabled),
            sort_key=lambda s: s.created_at,
            desc=True,
            limit=limit,
            offset=offset,
        )

    async def count_for_org(self, org_id: uuid.UUID, *, enabled: bool | None = None) -> int:
        return await self.table.count(
            filter_fn=lambda s: s.deleted_at is None and (enabled is None or s.enabled == enabled)
        )

    async def list_enabled(self, org_id: uuid.UUID) -> list[Skill]:
        """本组织已启用 skills（主 agent 自动使用，镜像 tools list_enabled_names）。"""
        return await self.table.list(
            filter_fn=lambda s: s.enabled and s.deleted_at is None, sort_key=lambda s: s.name
        )

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
        self.table.register(skill)
        return skill

    async def soft_delete(self, skill: Skill) -> None:
        skill.deleted_at = datetime.now(UTC)
