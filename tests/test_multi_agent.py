"""B4/B5 多 Agent 测试（DB-backed）：proposer-reviewer 协作 + agent_switch 事件发射；single 回归。"""
from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.messages import AIMessage

from app.core.events import sse_emitter
from app.core.security import hash_password
from app.orchestration.graph import build_graph
from app.orchestration.stream_core import build_initial_state, stream_graph_events
from app.storage.db import init_db
from app.storage.models import AgentConfig, Org, User
from tests.conftest import requires_db

pytestmark = requires_db


class FakeMultiModel:
    """按 prompt 关键词返回不同内容（提案/评审/汇总）。"""

    def __init__(self, content="回答"):
        self.content = content
        self.calls: list[str] = []

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        text = "".join(str(getattr(m, "content", "") or "") for m in messages)
        self.calls.append(text[:24])
        if "方案提案者" in text:
            return AIMessage(content="【提案】三步方案")
        if "方案评审者" in text:
            return AIMessage(content="【评审】方案可行，补充风险")
        if "汇总者" in text:
            return AIMessage(content="【定稿】最终回答")
        return AIMessage(content=self.content)


@pytest.fixture
async def multi_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with sessionmaker() as session:
        org = Org(name=f"测试组织-ma-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"ma_{uid}", password_hash=hash_password("x"), name="T", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=org.id, name="协作助手", model="fake", system_prompt="你是助手。", tools=[], max_steps=5,
            status="published", graph_template="proposer_reviewer",
        )
        session.add(agent)
        await session.flush()
        single = AgentConfig(
            org_id=org.id, name="单 Agent", model="fake", system_prompt="你是助手。", tools=[], max_steps=5,
            status="published", graph_template="single",
        )
        session.add(single)
        await session.commit()
    yield sessionmaker, user, agent, single
    await engine.dispose()


def _events(frames: list[str]) -> list[dict]:
    out = []
    for f in frames:
        if f.startswith(":"):
            continue
        data = f.split("\n\n")[0].split("data: ", 1)[1]
        out.append(json.loads(data))
    return out


async def _on_final(fs):
    return {"message": fs.get("final_message", {})}


async def _run(graph, agent, user, content, fake):
    initial = build_initial_state(agent, content, user_id=str(user.id), org_id=str(agent.org_id))
    frames = []
    async for frame in stream_graph_events(
        graph=graph,
        initial=initial,
        graph_config={"configurable": {"model": fake}},
        emit=sse_emitter(),  # 与真实 chat_stream 一致的信封格式
        on_final=_on_final,
    ):
        frames.append(frame)
    return _events(frames)


async def test_proposer_reviewer_emits_agent_switch(multi_fixture):
    sessionmaker, user, agent, single = multi_fixture
    fake = FakeMultiModel()
    graph = build_graph()
    events = await _run(graph, agent, user, "写一份技术方案", fake)
    switches = [e for e in events if e["type"] == "agent_switch"]
    assert len(switches) == 3  # assistant→proposer / proposer→reviewer / reviewer→assistant
    assert switches[0]["payload"]["from_agent"] == "assistant"
    assert switches[0]["payload"]["to_agent"] == "proposer"
    assert switches[1]["payload"]["to_agent"] == "reviewer"
    assert switches[2]["payload"]["to_agent"] == "assistant"
    done = [e for e in events if e["type"] == "done"]
    assert done and done[0]["payload"]["message"]["content"] == "【定稿】最终回答"
    # 上下文隔离：proposer 只收任务，reviewer 只收草案（calls 长度 = 3 次 LLM）
    assert len(fake.calls) == 3


async def test_single_template_no_agent_switch(multi_fixture):
    sessionmaker, user, agent, single = multi_fixture
    fake = FakeMultiModel(content="单 Agent 回答")
    graph = build_graph()
    events = await _run(graph, single, user, "你好", fake)
    assert [e["type"] for e in events if e["type"] == "agent_switch"] == []  # 无切换事件
    done = [e for e in events if e["type"] == "done"]
    assert done[0]["payload"]["message"]["content"] == "单 Agent 回答"
