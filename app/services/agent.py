"""Agent 领域服务（docs 01 §5 services/agent.py）。M1 只读（POST/PUT 版本化为 M2 接缝）。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_AGENT_NOT_FOUND, AppError
from app.services.serializers import serialize_agent, serialize_agent_version
from app.storage.models.agent import AgentConfig
from app.storage.repositories.agent import AgentRepository


class AgentService:
    async def list_for_org(self, db: AsyncSession, org_id: uuid.UUID, page: int, page_size: int) -> dict[str, Any]:
        repo = AgentRepository(db)
        items = await repo.list_for_org(org_id, limit=page_size, offset=(page - 1) * page_size)
        total = await repo.count_for_org(org_id)
        from app.api.schemas.common import paged

        return paged([serialize_agent(a) for a in items], total, page, page_size)

    async def get_in_org(self, db: AsyncSession, agent_id: uuid.UUID, org_id: uuid.UUID) -> AgentConfig:
        agent = await AgentRepository(db).get_by_id(agent_id)
        if agent is None or str(agent.org_id) != str(org_id) or agent.deleted_at is not None:
            raise AppError(ERR_AGENT_NOT_FOUND, "Agent 不存在或无权访问")
        return agent

    async def get_published(self, db: AsyncSession, agent_id: uuid.UUID, org_id: uuid.UUID) -> AgentConfig:
        agent = await AgentRepository(db).get_published(agent_id)
        if agent is None or str(agent.org_id) != str(org_id):
            raise AppError(ERR_AGENT_NOT_FOUND, "Agent 不存在或未发布")
        return agent

    async def versions(self, db: AsyncSession, agent_id: uuid.UUID) -> list[dict[str, Any]]:
        vers = await AgentRepository(db).list_versions(agent_id)
        return [serialize_agent_version(v) for v in vers]
