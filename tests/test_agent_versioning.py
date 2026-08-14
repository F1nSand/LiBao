"""T8 Agent 版本化测试（DB-backed）：create draft+v1、PUT 新版本 append-only、publish 快照 hash、
unpublish、软删保留版本、invoke 试跑帧序且不落消息。

需要 Docker db；DB 不可达自动跳过。
"""
from __future__ import annotations

import json
import socket
import uuid

import pytest
from langchain_core.messages import AIMessage

from app.api.schemas.agents import AgentWriteRequest
from app.core.prefix import compute_prefix_hash
from app.core.security import hash_password
from app.orchestration.chat_stream import agent_invoke_events
from app.orchestration.graph import build_graph
from app.services.agent import AgentService
from app.storage.db import init_db
from app.storage.models import Org, User
from app.storage.repositories.agent import AgentRepository
from app.storage.repositories.conversation import ConversationRepository
from app.storage.repositories.message import MessageRepository


def _db_reachable() -> bool:
    try:
        with socket.create_connection(("localhost", 5432), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="Docker db 未运行")


class FakeChatModel:
    def __init__(self) -> None:
        self._n = 0

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        if self._n == 0:
            self._n = 1
            return AIMessage(
                content="", tool_calls=[{"name": "time_now", "args": {}, "id": "call_1", "type": "tool_call"}]
            )
        return AIMessage(content="试跑完成。")


@pytest.fixture
async def agent_fixture():
    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        org = Org(name=f"测试组织-agents-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"ag_{uid}", password_hash=hash_password("x"), name="A", role="admin", org_id=org.id)
        session.add(user)
        await session.commit()
    yield sessionmaker, user
    await engine.dispose()


def _req(**kw) -> AgentWriteRequest:
    base = {"name": "版本化助手", "model": "fake", "system_prompt": "你是版本化测试助手。", "tools": ["tl_time_now"]}
    base.update(kw)
    return AgentWriteRequest(**base)


async def test_create_draft_with_version_1(agent_fixture):
    sessionmaker, user = agent_fixture
    async with sessionmaker() as session:
        agent = await AgentService().create(session, user.org_id, _req())
        assert agent.status == "draft"
        assert agent.current_version == 1
        vers = await AgentService().versions(session, agent)
        assert len(vers) == 1
        assert vers[0]["version"] == 1
        assert vers[0]["config"]["name"] == "版本化助手"


async def test_update_creates_new_version_append_only(agent_fixture):
    sessionmaker, user = agent_fixture
    async with sessionmaker() as session:
        agent = await AgentService().create(session, user.org_id, _req())
        v1_content = agent.system_prompt
        agent = await AgentService().update(session, agent, _req(name="版本化助手v2", system_prompt="新提示词"))
        assert agent.current_version == 2
        vers = await AgentService().versions(session, agent)
        assert len(vers) == 2
        v1 = next(v for v in vers if v["version"] == 1)
        assert v1["config"]["system_prompt"] == v1_content  # append-only：v1 内容不变


async def test_publish_creates_snapshot_with_prefix_hash(agent_fixture):
    sessionmaker, user = agent_fixture
    async with sessionmaker() as session:
        agent = await AgentService().create(session, user.org_id, _req())
        agent = await AgentService().publish(session, agent)
        assert agent.status == "published"
        assert agent.current_version == 2  # create v1 + publish v2
        vers = await AgentService().versions(session, agent)
        v2 = next(v for v in vers if v["version"] == 2)
        expected = compute_prefix_hash(agent.model, agent.system_prompt, sorted(agent.tools or []))
        assert v2["prefix_hash"] == expected


async def test_unpublish_and_soft_delete(agent_fixture):
    sessionmaker, user = agent_fixture
    async with sessionmaker() as session:
        agent = await AgentService().create(session, user.org_id, _req())
        agent = await AgentService().publish(session, agent)
        agent = await AgentService().unpublish(session, agent)
        assert agent.status == "disabled"
        await AgentService().soft_delete(session, agent)
        # 软删后 get_in_org → 40404，但版本列表仍可查
        from app.core.errors import AppError

        with pytest.raises(AppError) as exc:
            await AgentService().get_in_org(session, agent.id, user.org_id)
        assert exc.value.code == 40404
        vers = await AgentRepository(session).list_versions(agent.id)
        assert len(vers) == 2  # 版本保留


async def test_invoke_streams_without_persisting(agent_fixture):
    sessionmaker, user = agent_fixture
    graph = build_graph()
    async with sessionmaker() as session:
        agent = await AgentService().create(session, user.org_id, _req())
        # 试跑不落会话/消息：先确认库里没有任何会话
        convs_before = await ConversationRepository(session).list_by_user(user.id)
        frames = []
        async for frame in agent_invoke_events(
            db=session,
            graph=graph,
            agent=agent,
            user=user,
            content="现在几点？",
            trace_id="trace-invoke",
            model_override=FakeChatModel(),
        ):
            frames.append(frame)
        events = []
        for frame in frames:
            if frame.startswith(":"):
                continue
            data = frame.split("\n\n")[0].split("data: ", 1)[1]
            events.append(json.loads(data))
        types = [e["type"] for e in events]
        assert types[0] == "message_start"
        assert "tool_call" in types and "tool_result" in types and "token" in types
        assert types[-1] == "done"
        # 不落消息/会话
        convs_after = await ConversationRepository(session).list_by_user(user.id)
        assert len(convs_after) == len(convs_before)
        msgs_total = 0
        for conv in convs_after:
            msgs_total += await MessageRepository(session).count(conv.id)
        assert msgs_total == 0
