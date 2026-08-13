"""Agent 配置数据访问（docs 04 §3.4）。对话侧只暴露 published 的 agent；版本为只读快照。"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.agent import AgentConfig, AgentVersion


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, agent_id: uuid.UUID) -> AgentConfig | None:
        return await self.session.get(AgentConfig, agent_id)

    async def get_published(self, agent_id: uuid.UUID) -> AgentConfig | None:
        """取已发布 agent；非 published/已软删返回 None（上层映射 40404）。"""
        stmt = select(AgentConfig).where(
            AgentConfig.id == agent_id,
            AgentConfig.status == "published",
            AgentConfig.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_published(
        self, org_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> list[AgentConfig]:
        stmt = (
            select(AgentConfig)
            .where(
                AgentConfig.org_id == org_id,
                AgentConfig.status == "published",
                AgentConfig.deleted_at.is_(None),
            )
            .order_by(AgentConfig.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def list_versions(self, agent_id: uuid.UUID) -> list[AgentVersion]:
        stmt = (
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id, AgentVersion.deleted_at.is_(None))
            .order_by(AgentVersion.version.desc())
        )
        return list((await self.session.execute(stmt)).scalars())
