"""T5 图级 interrupt/resume 测试（InMemorySaver，无 DB）：触发中断、确认续跑、拒绝取消。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command, Interrupt

from app.orchestration.graph import build_graph
from app.tools import executor
from app.tools.registry import ToolSpec, register, unregister
from app.tools.sandbox import SandboxCommand, SandboxLevel, SandboxResult


class FakeChatModel:
    def __init__(self, tool_name: str = "confirm_test") -> None:
        self._n = 0
        self.tool_name = tool_name

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        if self._n == 0:
            self._n = 1
            return AIMessage(
                content="",
                tool_calls=[{"name": self.tool_name, "args": {"msg": "hi"}, "id": "call_1", "type": "tool_call"}],
            )
        return AIMessage(content="已按确认结果处理。")


@pytest.fixture
def confirm_tool():
    # 幂等：I6 后 register 拒同名遮蔽，进程内多次注册必须先摘除
    unregister("tl_confirm_test")
    register(
        ToolSpec(
            id="tl_confirm_test",
            name="confirm_test",
            description="需人工确认的演示工具",
            params_schema={"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
            require_confirm=True,
            enabled=True,
            handler=lambda msg: {"delivered": True, "msg": msg},
        )
    )
    yield
    unregister("tl_confirm_test")


@pytest.fixture
def docker_confirm_tool():
    unregister("tl_docker_confirm_test")

    async def build_command(**kwargs):
        return SandboxCommand(argv=("bash", "-lc", "echo approved"))

    register(
        ToolSpec(
            id="tl_docker_confirm_test",
            name="docker_confirm_test",
            description="需确认的 Docker 工具",
            params_schema={"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]},
            require_confirm=True,
            enabled=True,
            sandbox=SandboxLevel.DOCKER,
            sandbox_command_builder=build_command,
        )
    )
    yield
    unregister("tl_docker_confirm_test")


def _agent_config() -> dict:
    return _agent_config_for("tl_confirm_test")


def _agent_config_for(tool_id: str) -> dict:
    return {
        "model": "fake",
        "system_prompt": "你是测试助手。",
        "tools": [tool_id],
        "max_steps": 5,
    }


async def _run_to_interrupt(graph, fake, thread_id: str, tool_id: str = "tl_confirm_test"):
    """跑图到 interrupt 暂停点，返回 (interrupt_value, config)。"""
    config = {"configurable": {"thread_id": thread_id, "model": fake}}
    updates = []
    async for item in graph.astream(
            {"messages": [HumanMessage(content="发消息")], "agent_config": _agent_config_for(tool_id)},
        config,
        stream_mode=["updates"],
    ):
        # 单模式 updates 产出 ("updates", {node: update}) 元组；取 payload dict
        updates.append(item[1])
    interrupt_entry = next(u["__interrupt__"][0] for u in updates if "__interrupt__" in u)
    assert isinstance(interrupt_entry, Interrupt)
    return interrupt_entry.value, config


async def test_interrupt_triggered(confirm_tool):
    graph = build_graph(checkpointer=MemorySaver())
    value, _ = await _run_to_interrupt(graph, FakeChatModel(), "t5-thread-1")
    assert value["tool_call_id"] == "call_1"
    assert value["tool_name"] == "confirm_test"
    assert value["confirm_required"] is True


async def test_resume_approved_continues(confirm_tool):
    graph = build_graph(checkpointer=MemorySaver())
    fake = FakeChatModel()
    _, config = await _run_to_interrupt(graph, fake, "t5-thread-2")

    async for _ in graph.astream(Command(resume={"approved": True}), config, stream_mode=["updates"]):
        pass

    state = await graph.aget_state(config)
    fm = state.values["final_message"]
    assert fm["tool_calls"][0]["status"] == "done"
    assert fm["tool_calls"][0]["output"]["delivered"] is True
    assert "已按确认结果处理" in fm["content"]


async def test_resume_denied_cancels(confirm_tool):
    graph = build_graph(checkpointer=MemorySaver())
    fake = FakeChatModel()
    _, config = await _run_to_interrupt(graph, fake, "t5-thread-3")

    async for _ in graph.astream(Command(resume={"approved": False}), config, stream_mode=["updates"]):
        pass

    state = await graph.aget_state(config)
    fm = state.values["final_message"]
    assert fm["tool_calls"][0]["status"] == "cancelled"
    assert fm["tool_calls"][0]["output"] is None
    # 消息流含 tool 角色（cancelled ToolMessage）
    roles = [m.type for m in state.values["messages"]]
    assert "tool" in roles


async def test_docker_tool_denied_creates_no_container(monkeypatch, docker_confirm_tool):
    graph = build_graph(checkpointer=MemorySaver())
    fake = FakeChatModel(tool_name="docker_confirm_test")
    _, config = await _run_to_interrupt(graph, fake, "docker-denied", "tl_docker_confirm_test")
    calls = []

    async def runner(*args, **kwargs):
        calls.append((args, kwargs))
        return SandboxResult(exit_code=0, stdout="ok", stderr="")

    monkeypatch.setattr(executor, "run_docker_command", runner)
    async for _ in graph.astream(Command(resume={"approved": False}), config, stream_mode=["updates"]):
        pass
    assert calls == []


async def test_docker_tool_approved_creates_exactly_one_container(monkeypatch, docker_confirm_tool, tmp_path):
    graph = build_graph(checkpointer=MemorySaver())
    fake = FakeChatModel(tool_name="docker_confirm_test")
    _, config = await _run_to_interrupt(graph, fake, "docker-approved", "tl_docker_confirm_test")
    calls = []

    async def runner(*args, **kwargs):
        calls.append((args, kwargs))
        return SandboxResult(exit_code=0, stdout="approved", stderr="")

    monkeypatch.setattr(executor, "run_docker_command", runner)
    monkeypatch.setattr(executor, "get_tool_workspace_root", lambda: str(tmp_path), raising=False)
    async for _ in graph.astream(Command(resume={"approved": True}), config, stream_mode=["updates"]):
        pass
    assert len(calls) == 1
