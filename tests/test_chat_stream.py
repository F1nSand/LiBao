"""T10 SSE 桥测试：精确信封序列（message_start→tool_call→tool_result→token→status→done）+ 消息持久化。

需要 Docker db（localhost:5432）；DB 不可达时自动跳过（review gate 无 DB 也能跑其余测试）。
"""
from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.messages import AIMessage

from app.orchestration.chat_stream import chat_stream_events
from app.orchestration.graph import build_graph
from app.storage.db import init_db
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, Conversation, Org, User
from app.storage.repositories.message import MessageRepository
from tests.conftest import requires_db

pytestmark = requires_db


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
        return AIMessage(content="现在是 2026 年 8 月 13 日 21:00。")


@pytest.fixture
async def chat_fixture():
    engine, sessionmaker = init_db()
    uid = uuid.uuid4().hex[:8]
    async with get_store().session(sessionmaker) as session:
        org = Org(name=f"测试组织-t10-{uid}")
        session.add(org)
        await session.flush()
        user = User(username=f"t10_{uid}", password_hash="hashed", name="T10", role="admin", org_id=org.id)
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=org.id,
            name="T10时间助手",
            model="fake",
            system_prompt="你是时间助手。",
            tools=["tl_time_now"],
            max_steps=5,
            status="published",
        )
        session.add(agent)
        await session.flush()
        conv = Conversation(user_id=user.id, agent_id=agent.id, title="t10会话")
        session.add(conv)
        await session.commit()
    yield sessionmaker, org, user, agent, conv
    await engine.dispose()


async def test_chat_stream_event_sequence(chat_fixture):
    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    sessionmaker, org, user, agent, conv = chat_fixture
    graph = build_graph()

    async with get_store().session(sessionmaker) as session:
        frames = []
        async for frame in chat_stream_events(
            db=session,
            graph=graph,
            conversation=conv,
            agent=agent,
            user=user,
            content="现在几点？",
            trace_id="trace-t10",
            model_override=FakeChatModel(),
        ):
            frames.append(frame)

        events = []
        for frame in frames:
            if frame.startswith(":"):  # keepalive 注释跳过
                continue
            data = frame.split("\n\n")[0].split("data: ", 1)[1]
            events.append(json.loads(data))

        types = [e["type"] for e in events]
        assert types[0] == "message_start"
        assert "tool_call" in types and "tool_result" in types and "token" in types
        assert "status" in types
        assert types[-1] == "done"
        seqs = [e["seq"] for e in events]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

        tool_call = next(e for e in events if e["type"] == "tool_call")
        assert tool_call["payload"]["tool_name"] == "time_now"
        tool_result = next(e for e in events if e["type"] == "tool_result")
        assert tool_result["payload"]["ok"] is True
        # 逐轮消息（docs 03 §3）：第 1 轮（工具）发 message 事件；最终轮由 done 承载
        seal = next(e for e in events if e["type"] == "message")
        assert seal["payload"]["message"]["round"] == 1
        assert seal["payload"]["message"]["tool_calls"][0]["tool_name"] == "time_now"
        done = events[-1]
        assert done["payload"]["message"]["role"] == "assistant"
        assert done["payload"]["message"]["round"] == 2

        msgs = await MessageRepository(session).list_by_conversation(conv.id)
        roles = [m.role for m in msgs]
        assert roles == ["user", "assistant", "assistant"]  # 工具轮 + 最终轮各一条
        assert msgs[0].content == "现在几点？"
        assert msgs[1].round == 1 and msgs[1].tool_calls and msgs[1].tool_calls[0]["tool_name"] == "time_now"
        assert msgs[2].round == 2 and msgs[2].tool_calls == []
        assert msgs[1].trace_id == "trace-t10"


async def test_message_seal_carries_cost(chat_fixture):
    """逐轮 cost 表面化（M6-2）：message 封口事件与 done 消息均含 cost（Fake 无 usage → 0.0）。"""
    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    sessionmaker, org, user, agent, conv = chat_fixture
    graph = build_graph()

    async with get_store().session(sessionmaker) as session:
        frames = []
        async for frame in chat_stream_events(
            db=session, graph=graph, conversation=conv, agent=agent, user=user,
            content="现在几点？", trace_id="trace-t10-cost", model_override=FakeChatModel(),
        ):
            frames.append(frame)

        events = []
        for frame in frames:
            if frame.startswith(":"):
                continue
            events.append(json.loads(frame.split("\n\n")[0].split("data: ", 1)[1]))

        seal = next(e for e in events if e["type"] == "message")
        assert seal["payload"]["cost"] == 0.0
        assert seal["payload"]["message"]["cost"] == 0.0
        done = events[-1]
        assert done["payload"]["message"]["cost"] == 0.0


async def test_thinking_event_and_persistence(chat_fixture):
    """thinking（reasoning_content）：SSE 发射 + 按轮持久化（docs 03 §3）。"""

    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    sessionmaker, org, user, agent, conv = chat_fixture

    class ThinkingModel(FakeChatModel):
        async def ainvoke(self, messages):
            resp: AIMessage = await super().ainvoke(messages)
            resp.additional_kwargs["reasoning_content"] = "我在思考调用时间工具。"
            return resp

    graph = build_graph()
    async with get_store().session(sessionmaker) as session:
        frames = []
        async for frame in chat_stream_events(
            db=session, graph=graph, conversation=conv, agent=agent, user=user,
            content="现在几点？", trace_id="trace-think", model_override=ThinkingModel(),
        ):
            frames.append(frame)

        events = []
        for frame in frames:
            if frame.startswith(":"):
                continue
            data = frame.split("\n\n")[0].split("data: ", 1)[1]
            events.append(json.loads(data))
        think_events = [e for e in events if e["type"] == "thinking"]
        assert think_events, "应发射 thinking 事件"
        assert think_events[0]["payload"]["text"] == "我在思考调用时间工具。"

        msgs = await MessageRepository(session).list_by_conversation(conv.id)
        # 即时落库：任务完成后 DB 已有全部轮次
        assert [m.role for m in msgs] == ["user", "assistant", "assistant"]
        assert msgs[1].thinking == "我在思考调用时间工具。"  # 工具轮
        assert msgs[2].thinking == "我在思考调用时间工具。"  # 最终轮
