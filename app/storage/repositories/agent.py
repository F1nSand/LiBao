"""Agent 配置数据访问（docs 04 §3.4）。单通用 Agent 模型：每组织一条 is_default=True 的通用 Agent。"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.agent import AgentConfig


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, agent_id: uuid.UUID) -> AgentConfig | None:
        return await self.session.get(AgentConfig, agent_id)

    async def get_default(self, org_id: uuid.UUID) -> AgentConfig | None:
        """取组织的默认通用 Agent（is_default=True 且 published 未软删）；
        回退：无 is_default 标记的旧数据 → 首个 published（存量兼容）。"""
        stmt = (
            select(AgentConfig)
            .where(
                AgentConfig.org_id == org_id,
                AgentConfig.is_default.is_(True),
                AgentConfig.status == "published",
                AgentConfig.deleted_at.is_(None),
            )
            .order_by(AgentConfig.created_at.desc())
        )
        agent = (await self.session.execute(stmt)).scalars().first()
        if agent is not None:
            return agent
        stmt = (
            select(AgentConfig)
            .where(
                AgentConfig.org_id == org_id,
                AgentConfig.status == "published",
                AgentConfig.deleted_at.is_(None),
            )
            .order_by(AgentConfig.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()
