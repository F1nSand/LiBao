"""Agent 配置数据访问（docs 04 §3.4）。单通用 Agent 模型：每组织一条 is_default=True 的通用 Agent。"""
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

    async def get_previous_version(self, agent_id: uuid.UUID, current_version: int) -> AgentVersion | None:
        """取当前版本之前的最近一版快照（回滚目标）。version < current_version 降序取 1。"""
        stmt = (
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id, AgentVersion.version < current_version)
            .order_by(AgentVersion.version.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_default(self, org_id: uuid.UUID, *, for_update: bool = False) -> AgentConfig | None:
        """取组织的默认通用 Agent（is_default=True 且 published 未软删）；
        回退：无 is_default 标记的旧数据 → 首个 published（存量兼容）。
        for_update=True 时加行锁（publish/rollback 用，防 current_version 并发读改写腐蚀账本）。"""
        base = select(AgentConfig).where(AgentConfig.status == "published", AgentConfig.deleted_at.is_(None))
        stmt = base.where(AgentConfig.org_id == org_id, AgentConfig.is_default.is_(True))
        if for_update:
            stmt = stmt.with_for_update()
        stmt = stmt.order_by(AgentConfig.created_at.desc())
        agent = (await self.session.execute(stmt)).scalars().first()
        if agent is not None:
            return agent
        stmt = base.where(AgentConfig.org_id == org_id)
        if for_update:
            stmt = stmt.with_for_update()
        stmt = stmt.order_by(AgentConfig.created_at.desc())
        return (await self.session.execute(stmt)).scalars().first()
