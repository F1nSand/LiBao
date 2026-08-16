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

# 单通用 Agent（docs 01 §3.5）：所有会话/任务固定用这一个，不能更换；subagent 由主 agent 自主派发。
# LLM 侧函数名为 time_now/demo_notify/dispatch_subagent（registry id 是 tl_ 前缀）——提示词里写模型实际见到的名字
AGENT_NAME = "通用助手"
AGENT_SYSTEM_PROMPT = (
    "你是通用助手，面向用户的通用 AI 助手。\n"
    "需要专业子任务时，用 dispatch_subagent 工具派发专家 subagent（subagent 只做该子任务，结论回传你收口）：\n"
    "- 需要检索知识库 / 抓取网页汇总资料时 → 派发「资料调研」research；\n"
    "- 需要审查代码、找缺陷或改进点时 → 派发「代码评审」code_review；\n"
    "- 需要评审方案 / 计划（可行性、风险、遗漏、更优解）时 → 派发「方案评审」proposal_review。\n"
    "派发后基于 subagent 结论继续回答用户，用中文回答。\n"
    "用户要求发送通知/提醒时使用 demo_notify 工具（该工具为演示人工确认流程：会先请求确认，确认后才真正发送）。"
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


async def _get_or_create_tool(
    session: AsyncSession,
    org: Org,
    *,
    name: str,
    description: str,
    params_schema: dict,
    tool_type: str,
    require_confirm: bool,
    idempotent: bool,
    enabled: bool = True,
    timeout_ms: int = 5000,
    max_concurrency: int = 10,
) -> ToolDefinition:
    stmt = select(ToolDefinition).where(
        ToolDefinition.org_id == org.id, ToolDefinition.name == name, ToolDefinition.deleted_at.is_(None)
    )
    tool = (await session.execute(stmt)).scalar_one_or_none()
    if tool is None:
        tool = ToolDefinition(
            org_id=org.id,
            name=name,  # registry id 为 tl_<name>，name 为 LLM 侧函数名
            description=description,
            params_schema=params_schema,
            tool_type=tool_type,
            enabled=enabled,
            require_confirm=require_confirm,
            idempotent=idempotent,
            sandbox="none",
            allowlist=None,
            timeout_ms=timeout_ms,
            max_concurrency=max_concurrency,
            mcp_source=None,
            version=1,
        )
        session.add(tool)
        await session.flush()
    else:
        # 幂等：目标态 enabled=显式传值
        tool.enabled = enabled
    return tool


async def _get_or_create_agent(
    session: AsyncSession,
    org: Org,
    *,
    name: str,
    prompt: str,
    tool_ids: list[str],
    is_default: bool = False,
) -> AgentConfig:
    stmt = select(AgentConfig).where(
        AgentConfig.org_id == org.id, AgentConfig.name == name, AgentConfig.deleted_at.is_(None)
    )
    agent = (await session.execute(stmt)).scalar_one_or_none()
    settings = get_settings()
    if agent is None:
        agent = AgentConfig(
            org_id=org.id,
            name=name,
            model=settings.llm_model,
            system_prompt=prompt,
            is_default=is_default,
            skills=[],
            tools=list(tool_ids),
            max_steps=10,
            status="published",
            current_version=0,
        )
        session.add(agent)
        await session.flush()
    else:
        # 幂等：确保目标态（重跑可修正旧版本种子）；缺失工具追加到最前
        agent.status = "published"
        agent.system_prompt = prompt
        agent.is_default = is_default
        missing = [t for t in tool_ids if t not in (agent.tools or [])]
        if missing:
            agent.tools = missing + list(agent.tools or [])
    return agent


async def _get_or_create_version(session: AsyncSession, agent: AgentConfig, tool_ids: list[str]) -> AgentVersion:
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
    ver.tools = list(tool_ids)
    ver.prefix_hash = compute_prefix_hash(agent.model, agent.system_prompt, tool_ids)
    if agent.current_version < 1:
        agent.current_version = 1
    return ver


async def main() -> None:
    engine, sessionmaker = init_db()
    async with sessionmaker() as session:
        org = await _get_or_create_org(session)
        for username, password, name, role in USERS:
            await _get_or_create_user(session, org, username, password, name, role)
        await _get_or_create_tool(
            session,
            org,
            name="time_now",
            description="获取当前时间。需要知道\"现在几点\"时使用，其他情况不要用。",
            params_schema={"type": "object", "properties": {}, "required": []},
            tool_type="perception",
            require_confirm=False,
            idempotent=False,  # 时间查询不可去重（缓存会返回陈旧时间）
        )
        await _get_or_create_tool(
            session,
            org,
            name="demo_notify",
            description="发送一条通知消息。演示人工确认流程：发送为不可逆/对外副作用操作，需用户确认后执行。",
            params_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "通知内容"},
                    "channel": {"type": "string", "description": "发送渠道，默认 default"},
                },
                "required": ["message"],
            },
            tool_type="user_comms",
            require_confirm=True,
            idempotent=True,
        )
        await _get_or_create_tool(
            session,
            org,
            name="tool_search",
            description="搜索平台已注册的工具目录（名称+路由描述），用于发现可用工具。",
            params_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "自然语言搜索关键词"}},
                "required": ["query"],
            },
            tool_type="perception",
            require_confirm=False,
            idempotent=False,
        )
        await _get_or_create_tool(
            session,
            org,
            name="kb_search",
            description="检索知识库（RAG）：按自然语言查询返回匹配的知识片段（含来源文档）。",
            params_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "自然语言检索问题"},
                    "collection_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "限定集合 id 列表；空 = 全部集合",
                    },
                    "top_k": {"type": "integer", "description": "返回条数，默认 5，上限 10"},
                    "semantic": {"type": "boolean", "description": "是否启用语义通道，默认 true"},
                    "bm25": {"type": "boolean", "description": "是否启用关键词通道，默认 true"},
                },
                "required": ["query"],
            },
            tool_type="perception",
            require_confirm=False,
            idempotent=False,
        )
        # M3.5 补齐：fetch_url / analyze_image 感知工具（docs 07 RM-8）——默认关闭，管理员显式启用
        await _get_or_create_tool(
            session,
            org,
            name="fetch_url",
            description="只读抓取网页内容（自动清洗正文）。需要访问外部 URL 获取信息时使用；受出站白名单限制。",
            params_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要抓取的 http/https URL"},
                    "max_chars": {"type": "integer", "description": "正文截断长度，默认 8000"},
                },
                "required": ["url"],
            },
            tool_type="perception",
            require_confirm=False,
            idempotent=False,
            enabled=False,
        )
        await _get_or_create_tool(
            session,
            org,
            name="analyze_image",
            description=(
                "分析已上传的附件（图片视觉降级文本 / 文本提取 / 文档元数据）。需要先上传附件拿到 attachment_id。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "attachment_id": {"type": "string", "description": "已上传附件的 id"},
                },
                "required": ["attachment_id"],
            },
            tool_type="perception",
            require_confirm=False,
            idempotent=False,
            enabled=False,
        )
        # 平台工具 DB 行（/tools 管理页可见可控）：dispatch_subagent（派发）/ initiate_demo（占位演示）默认启用
        await _get_or_create_tool(
            session,
            org,
            name="dispatch_subagent",
            description=(
                "派发专家 subagent 完成专业子任务（research 资料调研 / code_review 代码评审 / "
                "proposal_review 方案评审）；subagent 独立上下文只回传结论。"
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "subagent": {"type": "string", "description": "subagent 名"},
                    "task": {"type": "string", "description": "子任务描述"},
                    "context": {"type": "string", "description": "可选补充事实"},
                },
                "required": ["subagent", "task"],
            },
            tool_type="agent_control",
            require_confirm=False,
            idempotent=False,
            enabled=True,
        )
        await _get_or_create_tool(
            session,
            org,
            name="initiate_demo",
            description="发起一个演示后台任务：立即返回占位（job_ref），delay 秒后回填真值（占位/回填演示）。",
            params_schema={
                "type": "object",
                "properties": {
                    "delay": {"type": "integer", "description": "延迟秒数，默认 3"},
                    "note": {"type": "string", "description": "任务备注"},
                },
                "required": [],
            },
            tool_type="execution",
            require_confirm=False,
            idempotent=False,
            enabled=True,
        )
        # 单通用 Agent：挂齐感知 + 派发 + 异步占位演示工具（fetch_url/analyze_image 全局默认关，启用后即对通用助手开放）
        agent_tools = [
            "tl_time_now",
            "tl_demo_notify",
            "tl_tool_search",
            "tl_kb_search",
            "tl_fetch_url",
            "tl_analyze_image",
            "tl_dispatch_subagent",
            "tl_initiate_demo",
        ]
        agent = await _get_or_create_agent(
            session, org, name=AGENT_NAME, prompt=AGENT_SYSTEM_PROMPT, tool_ids=agent_tools, is_default=True
        )
        await _get_or_create_version(session, agent, agent_tools)
        # 存量收敛：旧「时间助手/协作助手」（多 Agent 模式遗留）禁用，避免与通用助手并存歧义
        for legacy_name in ("时间助手", "协作助手"):
            legacy = (
                await session.execute(
                    select(AgentConfig).where(
                        AgentConfig.org_id == org.id,
                        AgentConfig.name == legacy_name,
                        AgentConfig.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if legacy is not None:
                legacy.status = "disabled"
        await session.commit()
        print(
            f"seed ok: org={org.id} users={len(USERS)} "
            f"agent={agent.name}(v{agent.current_version}, status={agent.status}, is_default={agent.is_default})"
        )
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
