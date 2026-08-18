"""Agent 领域服务（docs 01 §5 services/agent.py）。

单通用 Agent 模型：所有会话/任务固定用组织默认通用 Agent，不再配置多 Agent/自选；
subagent 由主 Agent 经 tl_dispatch_subagent 自主派发（内置注册表 app/agents/registry.py）。
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERR_AGENT_NOT_FOUND, ERR_AGENT_ROLLBACK_UNAVAILABLE, AppError
from app.core.prefix import compute_prefix_hash
from app.storage.models.agent import AgentConfig, AgentVersion
from app.storage.repositories.agent import AgentRepository


class AgentService:
    async def get_default(self, db: AsyncSession, org_id: uuid.UUID) -> AgentConfig:
        agent = await AgentRepository(db).get_default(org_id)
        if agent is None:
            raise AppError(ERR_AGENT_NOT_FOUND, "默认 Agent 不存在或未发布")
        return agent

    async def publish_prompt(self, db: AsyncSession, org_id: uuid.UUID, system_prompt: str) -> AgentConfig:
        """发布新 system_prompt：只增版本快照（镜像 memory add_version）。**不 commit**，由调用方单事务提交。"""
        agent = await AgentRepository(db).get_default(org_id, for_update=True)
        if agent is None:
            raise AppError(ERR_AGENT_NOT_FOUND, "默认 Agent 不存在或未发布")
        agent.system_prompt = system_prompt
        agent.current_version += 1
        db.add(
            AgentVersion(
                agent_id=agent.id,
                version=agent.current_version,
                system_prompt=system_prompt,
                model=agent.model,
                tools=list(agent.tools or []),
                skills=list(agent.skills or []),
                prefix_hash=compute_prefix_hash(agent.model, system_prompt, list(agent.tools or [])),
            )
        )
        return agent

    async def rollback_prompt(self, db: AsyncSession, org_id: uuid.UUID) -> AgentConfig:
        """回滚到上一版快照：把 prev 内容作为新版本只增写入（失败版快照保留、不删）。**不 commit**。"""
        agent = await AgentRepository(db).get_default(org_id, for_update=True)
        if agent is None:
            raise AppError(ERR_AGENT_NOT_FOUND, "默认 Agent 不存在或未发布")
        prev = await AgentRepository(db).get_previous_version(agent.id, agent.current_version)
        if prev is None:
            raise AppError(ERR_AGENT_ROLLBACK_UNAVAILABLE, "无可回滚的上一版本")
        agent.system_prompt = prev.system_prompt
        agent.model = prev.model
        agent.tools = list(prev.tools or [])
        agent.current_version += 1
        db.add(
            AgentVersion(
                agent_id=agent.id,
                version=agent.current_version,
                system_prompt=prev.system_prompt,
                model=prev.model,
                tools=list(prev.tools or []),
                skills=list(prev.skills or []),
                prefix_hash=compute_prefix_hash(prev.model, prev.system_prompt, list(prev.tools or [])),
            )
        )
        return agent
