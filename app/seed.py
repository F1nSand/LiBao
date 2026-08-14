"""幂等种子数据（docs 05 §2.2）。运行：`uv run python -m app.seed`。

内容对齐 FrontEnd mock（src/mock/db.ts）：org + 3 用户（admin/dev/viewer）+ tl_time_now 工具 + 1 个已发布 Agent。
所有实体按业务键查找，存在即跳过（enabled/status 仅保证目标态），可重复执行。
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.prefix import compute_prefix_hash
from app.core.security import hash_password
from app.storage.base import Base  # noqa: F401  确保 Base.metadata 已注册
from app.storage.db import init_db
from app.storage.models import AgentConfig, AgentVersion, Org, ToolDefinition, User

USERS = [
    ("admin", "admin123", "管理员", "admin"),
    ("dev", "dev123", "开发者", "developer"),
    ("viewer", "viewer123", "访客", "viewer"),
]

# LLM 侧函数名为 time_now（registry id 是 tl_time_now）——提示词里写模型实际见到的名字
AGENT_NAME = "时间助手"
AGENT_SYSTEM_PROMPT = (
    "你是时间助手，只回答与时间相关的问题。"
    "需要知道当前时间时使用 time_now 工具，再基于工具结果回答。"
)


async def _get_or_create_org(session: AsyncSession) -> Org:
    stmt = select(Org).where(Org.name == "默认组织", Org.deleted_at.is_(None))
    org = (await session.execute(stmt)).scalar_one_or_none()
    if org is None:
        org = Org(name="默认组织")
        session.add(org)
        await session.flush()
    return org


async def _get_or_create_user(
    session: AsyncSession, org: Org, username: str, password: str, name: str, role: str
) -> User:
    stmt = select(User).where(User.username == username, User.deleted_at.is_(None))
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        user = User(
            username=username,
            password_hash=hash_password(password),
            name=name,
            role=role,
            org_id=org.id,
            enabled=True,
        )
        session.add(user)
        await session.flush()
    return user


async def _get_or_create_tool(session: AsyncSession, org: Org) -> ToolDefinition:
    stmt = select(ToolDefinition).where(ToolDefinition.name == "time_now", ToolDefinition.deleted_at.is_(None))
    tool = (await session.execute(stmt)).scalar_one_or_none()
    if tool is None:
        tool = ToolDefinition(
            org_id=org.id,
            name="time_now",  # registry id 为 tl_time_now，name 为 LLM 侧函数名
            description="获取当前时间。需要知道\"现在几点\"时使用，其他情况不要用。",
            params_schema={"type": "object", "properties": {}, "required": []},
            tool_type="perception",
            enabled=True,
            require_confirm=False,
            idempotent=True,
            sandbox="none",
            allowlist=None,
            timeout_ms=5000,
            max_concurrency=10,
            mcp_source=None,
            version=1,
        )
        session.add(tool)
        await session.flush()
    else:
        # 幂等：目标态 enabled=true
        tool.enabled = True
    return tool


async def _get_or_create_agent(session: AsyncSession, org: Org, tool_id: str) -> AgentConfig:
    stmt = select(AgentConfig).where(AgentConfig.name == AGENT_NAME, AgentConfig.deleted_at.is_(None))
    agent = (await session.execute(stmt)).scalar_one_or_none()
    settings = get_settings()
    if agent is None:
        agent = AgentConfig(
            org_id=org.id,
            name=AGENT_NAME,
            model=settings.llm_model,
            system_prompt=AGENT_SYSTEM_PROMPT,
            graph_template="single",
            skills=[],
            tools=[tool_id],
            max_steps=10,
            status="published",
            current_version=0,
        )
        session.add(agent)
        await session.flush()
    else:
        # 幂等：确保目标态（重跑可修正旧版本种子）
        agent.status = "published"
        agent.system_prompt = AGENT_SYSTEM_PROMPT
        if tool_id not in (agent.tools or []):
            agent.tools = [tool_id] + list(agent.tools or [])
    return agent


async def _get_or_create_version(session: AsyncSession, agent: AgentConfig, tool_id: str) -> AgentVersion:
    stmt = select(AgentVersion).where(
        AgentVersion.agent_id == agent.id, AgentVersion.version == 1, AgentVersion.deleted_at.is_(None)
    )
    ver = (await session.execute(stmt)).scalar_one_or_none()
    if ver is None:
        ver = AgentVersion(agent_id=agent.id, version=1, skills=[])
        session.add(ver)
    # 幂等：种子引导数据非真实发布版本，每次重跑刷新快照保持一致（赋值只写一次）
    ver.system_prompt = agent.system_prompt
    ver.model = agent.model
    ver.tools = [tool_id]
    ver.prefix_hash = compute_prefix_hash(agent.model, agent.system_prompt, [tool_id])
    if agent.current_version < 1:
        agent.current_version = 1
    return ver


async def main() -> None:
    engine, sessionmaker = init_db()
    async with sessionmaker() as session:
        org = await _get_or_create_org(session)
        for username, password, name, role in USERS:
            await _get_or_create_user(session, org, username, password, name, role)
        tool = await _get_or_create_tool(session, org)
        agent = await _get_or_create_agent(session, org, "tl_time_now")
        await _get_or_create_version(session, agent, "tl_time_now")
        await session.commit()
        print(
            f"seed ok: org={org.id} users={len(USERS)} tool={tool.name} "
            f"agent={agent.name}(v{agent.current_version}, status={agent.status})"
        )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
