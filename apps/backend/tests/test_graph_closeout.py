"""M8.1 阶段 B：轮次收口修复——finalize 兜底 + max_steps 收口轮（2026-08-24）。

回归场景：主 agent 步数到顶后最后答复不再 = 工具结果 JSON（裸收尾）。
"""

from __future__ import annotations

import uuid

from langchain_core.messages import AIMessage, ToolMessage

from app.orchestration.graph import build_graph
from app.orchestration.nodes.finalize import finalize_node


def _state(messages: list) -> dict:
    return {
        "messages": messages,
        "agent_config": {
            "name": "t",
            "model": "fake",
            "system_prompt": "你是助手。",
            "tools": ["tl_time_now"],
            "max_steps": 3,
        },
        "flags": {"steps": 2},
        "totals": {},
        "run_logs": [],
        "tool_results": [],
    }


# ---- finalize 兜底单测 ----


async def test_finalize_normal_ai_last_is_used():
    st = _state([AIMessage(content="先看看"), AIMessage(content="最终答复")])
    out = await finalize_node(st)
    assert out["final_message"]["content"] == "最终答复"
    assert "max_steps_exceeded" not in out["flags"]


async def test_finalize_falls_back_to_last_ai_text_when_last_is_tool_result():
    """末条是 ToolMessage（步数守卫强制退出）→ 回退最近 AI 文本，绝不把工具结果当答复。"""
    st = _state(
        [
            AIMessage(content="我来调用工具"),
            ToolMessage(content='{"output": "x"}', tool_call_id="c1"),
        ]
    )
    out = await finalize_node(st)
    assert out["final_message"]["content"] == "我来调用工具"
    assert "max_steps_exceeded" not in out["flags"]


async def test_finalize_placeholder_when_no_ai_text():
    """全为工具消息（极端）→ 占位 + max_steps_exceeded flag。"""
    tool_call = {"name": "t", "args": {}, "id": "c1"}
    st = _state([AIMessage(content="", tool_calls=[tool_call]), ToolMessage(content="r", tool_call_id="c1")])
    out = await finalize_node(st)
    assert "未生成最终答复" in out["final_message"]["content"]
    assert out["flags"]["max_steps_exceeded"] is True


# ---- graph 收口轮集成 ----


class _AlwaysToolsModel:
    """永远请求工具（无文本）——模拟超预算不收敛的模型。"""

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        return AIMessage(
            content="",
            tool_calls=[{"name": "time_now", "args": {}, "id": f"call_{uuid.uuid4().hex[:8]}", "type": "tool_call"}],
        )


class _AnswerAtBudgetModel:
    """第 1-2 轮调工具，第 3 轮（= max_steps，含收口提示）直接答复。"""

    def __init__(self) -> None:
        self._n = 0

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        self._n += 1
        if self._n <= 2:
            return AIMessage(
                content="",
                tool_calls=[{"name": "time_now", "args": {}, "id": f"call_{self._n}", "type": "tool_call"}],
            )
        return AIMessage(content="任务已完成，这是最终答复。")


async def _run_graph(model, initial: dict) -> dict:
    from app.tools.builtin import register_builtin_tools

    register_builtin_tools()
    graph = build_graph()
    return await graph.ainvoke(initial, {"configurable": {"model": model, "thread_id": str(uuid.uuid4())}})


def _initial(max_steps: int = 3) -> dict:
    return {
        "messages": [],
        "agent_config": {
            "name": "t",
            "model": "fake",
            "system_prompt": "你是助手。",
            "tools": ["tl_time_now"],
            "max_steps": max_steps,
        },
        "flags": {},
        "totals": {},
        "run_logs": [],
        "tool_results": [],
    }


async def test_graph_closeout_round_prevents_tool_result_as_final():
    """max_steps 到顶：多跑一轮收口轮；最终答复不回退成工具结果，而是占位 + flag。"""
    out = await _run_graph(_AlwaysToolsModel(), _initial(max_steps=3))
    fm = out["final_message"]
    assert "未生成最终答复" in fm["content"]
    assert out["flags"]["max_steps_exceeded"] is True
    # 3 轮工具都执行了（含第 3 轮 == max_steps，不是静默丢弃）：messages 里 3 条 ToolMessage
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 3


async def test_graph_answer_at_budget_round():
    """第 3 轮（= max_steps，收口提示生效）直接答复 → 正常收尾，无 flag。"""
    out = await _run_graph(_AnswerAtBudgetModel(), _initial(max_steps=3))
    assert out["final_message"]["content"] == "任务已完成，这是最终答复。"
    assert "max_steps_exceeded" not in out["flags"]
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 2
