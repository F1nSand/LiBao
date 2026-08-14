"""Agent 领域服务（docs 01 §5 services/agent.py）。M2：读写 + 版本化（PUT=新版本，publish=发布快照）。"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_AGENT_NOT_FOUND, AppError
from app.core.prefix import compute_prefix_hash
from app.services.serializers import serialize_agent, serialize_agent_version
from app.storage.models.agent import AgentConfig, AgentVersion
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
        if agent is None or agent.org_id != org_id or agent.deleted_at is not None:
            raise AppError(ERR_AGENT_NOT_FOUND, "Agent 不存在或无权访问")
        return agent

    async def get_published(self, db: AsyncSession, agent_id: uuid.UUID, org_id: uuid.UUID) -> AgentConfig:
        agent = await AgentRepository(db).get_published(agent_id)
        if agent is None or agent.org_id != org_id:
            raise AppError(ERR_AGENT_NOT_FOUND, "Agent 不存在或未发布")
        return agent

    async def versions(self, db: AsyncSession, agent: AgentConfig) -> list[dict[str, Any]]:
        vers = await AgentRepository(db).list_versions(agent.id)
        return [serialize_agent_version(v, name=agent.name) for v in vers]

    # ---- M2 写操作（版本化）----

    async def _snapshot(self, db: AsyncSession, agent: AgentConfig) -> AgentVersion:
        """append-only 版本快照（docs 04 §3.4）：prefix_hash 供静态前缀缓存键。"""
        ver = AgentVersion(
            agent_id=agent.id,
            version=agent.current_version + 1,
            system_prompt=agent.system_prompt,
            model=agent.model,
            tools=agent.tools or [],
            skills=agent.skills or [],
            prefix_hash=compute_prefix_hash(agent.model, agent.system_prompt, agent.tools or []),
        )
        db.add(ver)
        agent.current_version += 1
        await db.flush()
        return ver

    async def create(self, db: AsyncSession, org_id: uuid.UUID, req: Any) -> AgentConfig:
        if not req.name or not req.model:
            raise AppError(40001, "name 与 model 必填")
        agent = AgentConfig(
            org_id=org_id,
            name=req.name,
            model=req.model,
            system_prompt=req.system_prompt or "",
            graph_template=req.graph_template or "single",
            skills=req.skills or [],
            tools=req.tools or [],
            max_steps=req.max_steps or 50,
            status="draft",
            current_version=0,
        )
        db.add(agent)
        await db.flush()
        await self._snapshot(db, agent)
        await db.commit()
        await db.refresh(agent)
        return agent

    async def update(self, db: AsyncSession, agent: AgentConfig, req: Any) -> AgentConfig:
        for field in ("name", "model", "system_prompt", "skills", "tools", "graph_template", "max_steps"):
            value = getattr(req, field, None)
            if value is not None:
                setattr(agent, field, value)
        await db.flush()
        await self._snapshot(db, agent)  # PUT = 创建新版本（支持 A/B 与回滚）
        await db.commit()
        await db.refresh(agent)
        return agent

    async def publish(self, db: AsyncSession, agent: AgentConfig) -> AgentConfig:
        agent.status = "published"
        await db.flush()
        await self._snapshot(db, agent)  # 发布快照
        await db.commit()
        await db.refresh(agent)
        return agent

    async def unpublish(self, db: AsyncSession, agent: AgentConfig) -> AgentConfig:
        agent.status = "disabled"
        await db.commit()
        await db.refresh(agent)
        return agent

    async def soft_delete(self, db: AsyncSession, agent: AgentConfig) -> None:
        agent.deleted_at = datetime.now(UTC)
        await db.commit()
