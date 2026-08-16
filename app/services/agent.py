"""Agent 领域服务（docs 01 §5 services/agent.py）。

单通用 Agent 模型：所有会话/任务固定用组织默认通用 Agent，不再配置多 Agent/自选；
subagent 由主 Agent 经 tl_dispatch_subagent 自主派发（内置注册表 app/agents/registry.py）。
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_AGENT_NOT_FOUND, AppError
from app.storage.models.agent import AgentConfig
from app.storage.repositories.agent import AgentRepository


class AgentService:
    async def get_default(self, db: AsyncSession, org_id: uuid.UUID) -> AgentConfig:
        agent = await AgentRepository(db).get_default(org_id)
        if agent is None:
            raise AppError(ERR_AGENT_NOT_FOUND, "默认 Agent 不存在或未发布")
        return agent
