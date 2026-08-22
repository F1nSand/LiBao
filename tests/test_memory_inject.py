"""T5 记忆注入测试（DB-backed，图级）：memory_inject 节点 top-N 注入、渲染位置、
静默降级（桥未设不击穿对话）、run_log type=memory。
"""
from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.config import get_settings
from app.orchestration.context_builder import build_context
from app.orchestration.graph import build_graph
from app.orchestration.stream_core import build_initial_state
from app.services.memory import MemoryService
from app.storage.file.store import get_store
from app.storage.models import AgentConfig, User


class FakeModel:
    def __init__(self) -> None:
        self.last_messages: list | None = None

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        self.last_messages = messages
        return AIMessage(content="回答完成。")


@pytest.fixture
async def inject_fixture():
    uid = uuid.uuid4().hex[:8]
    async with get_store().session() as session:
        await session.flush()
        user = User(username=f"inj_{uid}", password_hash="hashed", name="T", role="admin", org_id=uuid.UUID(int=0))
        session.add(user)
        await session.flush()
        agent = AgentConfig(
            org_id=uuid.UUID(int=0), name="注入测试助手", model="fake", system_prompt="你是测试助手。",
            tools=[], max_steps=5, status="published",
        )
        session.add(agent)
        await session.commit()
    yield user, agent


def _agent_config(agent: AgentConfig) -> dict:
    return {
        "model": agent.model,
        "system_prompt": agent.system_prompt,
        "tools": agent.tools or [],
        "max_steps": agent.max_steps,
        "org_id": str(uuid.UUID(int=0)),
    }


async def test_no_user_id_injects_nothing(inject_fixture):
    user, agent = inject_fixture
    graph = build_graph()
    initial = build_initial_state(agent, "你好")  # user_id=None → 静默跳过
    result = await graph.ainvoke(initial, {"configurable": {"model": FakeModel()}})
    assert result["memory_refs"] == []


async def test_inject_cards_sorted_by_importance(inject_fixture):
    user, agent = inject_fixture
    async with get_store().session() as session:
        svc = MemoryService()
        await svc.create_card(session, user.id, "note", "低", {"text": "low"}, importance=0.2)
        await svc.create_card(session, user.id, "note", "高", {"text": "high"}, importance=0.9)
    graph = build_graph()
    model = FakeModel()
    initial = build_initial_state(agent, "你好", user_id=str(user.id))
    result = await graph.ainvoke(initial, {"configurable": {"model": model}})
    refs = result["memory_refs"]
    assert [r["title"] for r in refs] == ["高", "低"]  # importance desc
    assert refs[0]["content_text"] == '{"text": "high"}'


async def test_render_position_after_human_before_status_bar(inject_fixture):
    user, agent = inject_fixture
    async with get_store().session() as session:
        await MemoryService().create_card(session, user.id, "note", "卡", {"text": "x"}, importance=0.8)
    graph = build_graph()
    model = FakeModel()
    initial = build_initial_state(agent, "你好", user_id=str(user.id))
    await graph.ainvoke(initial, {"configurable": {"model": model}})
    # 用图返回的 state 重建渲染（memory_inject 写回的 refs）
    result_state = await graph.ainvoke(initial, {"configurable": {"model": FakeModel()}})
    msgs = build_context({**result_state, "flags": {"status_bar": "[状态]"}})
    texts = [m.content for m in msgs]
    human_idx = next(i for i, m in enumerate(msgs) if isinstance(m, HumanMessage))
    assert any(isinstance(m, SystemMessage) and "长期记忆" in m.content for m in msgs[human_idx + 1 :])
    status_idx = texts.index("[状态]")
    assert human_idx < status_idx  # 注入块在状态栏前


async def test_inject_limit_from_settings(inject_fixture, monkeypatch):
    user, agent = inject_fixture
    s = get_settings()
    monkeypatch.setattr(s, "memory_inject_limit", 1)
    async with get_store().session() as session:
        svc = MemoryService()
        await svc.create_card(session, user.id, "note", "a", {"text": "1"}, importance=0.5)
        await svc.create_card(session, user.id, "note", "b", {"text": "2"}, importance=0.9)
    graph = build_graph()
    initial = build_initial_state(agent, "你好", user_id=str(user.id))
    result = await graph.ainvoke(initial, {"configurable": {"model": FakeModel()}})
    assert len(result["memory_refs"]) == 1
    assert result["memory_refs"][0]["title"] == "b"


async def test_run_log_type_memory(inject_fixture):
    user, agent = inject_fixture
    async with get_store().session() as session:
        await MemoryService().create_card(session, user.id, "note", "卡", {"text": "x"})
    graph = build_graph()
    initial = build_initial_state(agent, "你好", user_id=str(user.id))
    result = await graph.ainvoke(initial, {"configurable": {"model": FakeModel()}})
    logs = result.get("run_logs") or []
    assert any(log.get("type") == "memory" and log.get("node") == "memory_inject" for log in logs)


async def test_full_chat_flow_with_injection(inject_fixture):
    user, agent = inject_fixture
    async with get_store().session() as session:
        await MemoryService().create_card(session, user.id, "note", "偏好", {"text": "用户喜欢喝茶"}, importance=0.7)
    graph = build_graph()
    model = FakeModel()
    initial = build_initial_state(agent, "你好", user_id=str(user.id))
    await graph.ainvoke(initial, {"configurable": {"model": model}})
    # 注入块作为 SystemMessage 出现在模型收到的消息里（HumanMessage 之后）
    sys_msgs = [m for m in model.last_messages if isinstance(m, SystemMessage)]
    assert any("用户喜欢喝茶" in m.content for m in sys_msgs)
