"""M4.5 subagent 派发测试（《02》后端设计 §3.5）：注册表 + 嵌套 LLM 循环 + agent_switch 事件（进入/离开）+ 子工具执行。

纯单测（不碰 DB）：dispatch ctx 注入假模型 / 事件汇；executor.execute 用 monkeypatch 桩（子工具不真跑）。
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, BaseMessage

from app.agents.registry import get_subagent, subagent_acis, subagent_names
from app.tools.builtin import register_builtin_tools
from app.tools.builtin.dispatch_subagent import dispatch_subagent_handler
from app.tools.context import get_dispatch_ctx, set_dispatch_ctx
from app.tools.executor import ToolResult
from app.tools.registry import set_enabled


class FakeChatModel:
    """可注入模型：bind_tools 记录 ACI；ainvoke 按序返回预设响应（无工具 → 单步收尾）。"""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self._i = 0
        self.bind_count = 0
        self.last_tools = None

    def bind_tools(self, tools, **kwargs):
        self.bind_count += 1
        self.last_tools = list(tools)
        return self

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        response = self._responses[self._i]
        self._i += 1
        return response


@pytest.fixture
def dispatch_ctx():
    """设置 dispatch ctx（事件汇 + 假模型）；yield 后清理（task-local 防串）。"""
    events: list[tuple[str, dict]] = []

    def push(event_type: str, payload: dict) -> str:
        events.append((event_type, payload))
        return ""

    def _install(model=None):
        ctx = {"push": push, "main_name": "通用助手"}
        if model is not None:
            ctx["model_builder"] = lambda *a, **k: model
        set_dispatch_ctx(ctx)
        return events

    yield _install, events
    set_dispatch_ctx(None)
    assert get_dispatch_ctx() is None


# ---- 注册表 ----

def test_get_subagent_lookup():
    spec = get_subagent("research")
    assert spec is not None
    assert spec.name == "research"
    assert spec.prompt and "调研" in spec.prompt
    assert "tl_kb_search" in spec.tools
    assert get_subagent("nope") is None
    assert set(subagent_names()) == {"research", "code_review", "proposal_review"}


def test_subagent_acis_resolves_enabled_tools():
    register_builtin_tools()
    spec = get_subagent("research")
    # 默认：fetch_url/analyze_image 全局关 → subagent 工具集也不含（管理员启用后才开放）
    names = {a["function"]["name"] for a in subagent_acis(spec)}
    assert names == {"kb_search", "tool_search"}
    set_enabled("tl_fetch_url", True)
    try:
        names2 = {a["function"]["name"] for a in subagent_acis(spec)}
        assert names2 == {"kb_search", "fetch_url", "tool_search"}
    finally:
        set_enabled("tl_fetch_url", False)


# ---- 嵌套 LLM 循环 + 事件 ----

async def test_handler_unknown_subagent_no_events(dispatch_ctx):
    install, events = dispatch_ctx
    install()
    result = await dispatch_subagent_handler(subagent="nope", task="查一下")
    assert "error" in result and "nope" in result["error"]
    assert events == []  # 未知名 → 不发 agent_switch


async def test_handler_single_answer_emits_two_switch(dispatch_ctx):
    register_builtin_tools()
    install, events = dispatch_ctx
    fake = FakeChatModel([AIMessage(content="调研结论：X 成立。")])
    install(fake)

    result = await dispatch_subagent_handler(subagent="research", task="调研 X")

    assert result["output"] == "调研结论：X 成立。"
    assert result["subagent"] == "research"
    assert result["steps"] == 1 and result["tool_calls"] == 0

    # 两次 agent_switch：进入（通用助手→research）与离开（research→通用助手）
    assert len(events) == 2
    assert events[0][0] == "agent_switch" and events[0][1]["from_agent"] == "通用助手"
    assert events[0][1]["to_agent"] == "research" and "调研" in events[0][1]["reason"]
    assert events[1][0] == "agent_switch" and events[1][1]["from_agent"] == "research"
    assert events[1][1]["to_agent"] == "通用助手"

    # subagent 工具 ACI 确实 bind 给了子循环（默认 fetch_url 关 → 不含）
    assert fake.bind_count == 1
    assert {a["function"]["name"] for a in fake.last_tools} == {"kb_search", "tool_search"}


async def test_handler_nested_loop_runs_sub_tools(dispatch_ctx, monkeypatch):
    register_builtin_tools()
    install, events = dispatch_ctx
    fake = FakeChatModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "kb_search", "args": {"query": "X"}, "id": "c1", "type": "tool_call"}],
            ),
            AIMessage(content="综合检索后结论。"),
        ]
    )
    install(fake)

    calls: list[dict] = []

    async def fake_execute(spec, input):
        calls.append({"name": spec.name, "input": input})
        return ToolResult(ok=True, output={"count": 1}, summary="检索到 1 条", duration_ms=10)

    monkeypatch.setattr("app.tools.builtin.dispatch_subagent.executor.execute", fake_execute)

    result = await dispatch_subagent_handler(subagent="research", task="检索 X")

    assert result["output"] == "综合检索后结论。"
    assert result["steps"] == 2 and result["tool_calls"] == 1
    assert len(calls) == 1 and calls[0]["name"] == "kb_search" and calls[0]["input"] == {"query": "X"}
    assert len(events) == 2  # 进入 + 离开（子工具执行不发额外 switch）


async def test_handler_context_isolated(dispatch_ctx):
    """上下文隔离：subagent 只见 SystemMessage(prompt) + HumanMessage(task)（+可选 context），不传主历史。"""
    register_builtin_tools()
    install, events = dispatch_ctx
    seen: list[list[str]] = []

    class RecordingModel(FakeChatModel):
        async def ainvoke(self, messages):
            seen.append([getattr(m, "type", "") + ":" + (m.content or "") for m in messages])
            return AIMessage(content="done")

    fake = RecordingModel([AIMessage(content="done")])
    install(fake)

    await dispatch_subagent_handler(subagent="code_review", task="审查这段代码", context="代码文件: src/a.py")

    msgs = seen[0]
    assert msgs[0].startswith("system:") and "代码评审" in msgs[0]
    assert msgs[1] == "human:审查这段代码"
    assert msgs[2] == "human:补充事实/上下文（来自主 Agent）：\n代码文件: src/a.py"
    assert len(msgs) == 3  # 无主 agent 历史泄漏


# ---- M8.1 阶段 C：预算耗尽收口（2026-08-24）----

_TOOL_RESP = AIMessage(
    content="",
    tool_calls=[{"name": "kb_search", "args": {"query": "X"}, "id": "c1", "type": "tool_call"}],
)


async def test_handler_budget_exhausted_forced_closeout(dispatch_ctx, monkeypatch):
    """max_steps 耗尽仍要工具 → 强制收口轮拿到结论（不再返回空 output）。"""
    register_builtin_tools()
    install, events = dispatch_ctx
    # 6 步工具调用 + 1 次强制收口（research max_steps=6）
    fake = FakeChatModel([_TOOL_RESP] * 6 + [AIMessage(content="收口结论：综合评估完成。")])
    install(fake)

    async def fake_execute(spec, input):
        return ToolResult(ok=True, output={"count": 1}, summary="检索到 1 条", duration_ms=10)

    monkeypatch.setattr("app.tools.builtin.dispatch_subagent.executor.execute", fake_execute)

    result = await dispatch_subagent_handler(subagent="research", task="检索 X")

    assert result["output"] == "收口结论：综合评估完成。"
    assert result["steps"] == 6
    assert result["tool_calls"] == 6
    assert "note" not in result


async def test_handler_budget_exhausted_fallback_placeholder(dispatch_ctx, monkeypatch):
    """强制收口轮仍不收敛（又要工具）→ 回退历史文本；历史全空 → 兜底文案 + note（绝不空 output）。"""
    register_builtin_tools()
    install, events = dispatch_ctx
    # 6 步工具调用 + 强制收口轮仍返回工具调用（无文本）
    fake = FakeChatModel([_TOOL_RESP] * 6 + [_TOOL_RESP])
    install(fake)

    async def fake_execute(spec, input):
        return ToolResult(ok=True, output={"count": 1}, summary="检索到 1 条", duration_ms=10)

    monkeypatch.setattr("app.tools.builtin.dispatch_subagent.executor.execute", fake_execute)

    result = await dispatch_subagent_handler(subagent="research", task="检索 X")

    assert result["output"].startswith("（subagent")
    assert "主 agent 请自行总结或重试" in result["output"]
    assert result["note"]
    assert result["steps"] == 6 and result["tool_calls"] == 6


async def test_handler_budget_exhausted_falls_back_to_last_text(dispatch_ctx, monkeypatch):
    """强制收口轮无文本 → 回退历史最后一段 AI 文本（不是空串）。"""
    register_builtin_tools()
    install, events = dispatch_ctx
    # 第 3 步「文本+工具」（有文本会继续循环）；6 步后强制收口轮仍返回工具调用（无文本）→ 回退
    text_with_tools = AIMessage(
        content="中间小结：已收集部分事实。",
        tool_calls=[{"name": "kb_search", "args": {"query": "X"}, "id": "c2", "type": "tool_call"}],
    )
    fake = FakeChatModel([_TOOL_RESP] * 2 + [text_with_tools] + [_TOOL_RESP] * 3 + [_TOOL_RESP])
    install(fake)

    async def fake_execute(spec, input):
        return ToolResult(ok=True, output={"count": 1}, summary="检索到 1 条", duration_ms=10)

    monkeypatch.setattr("app.tools.builtin.dispatch_subagent.executor.execute", fake_execute)

    result = await dispatch_subagent_handler(subagent="research", task="检索 X")

    assert result["output"] == "中间小结：已收集部分事实。"
    assert result["steps"] == 6
