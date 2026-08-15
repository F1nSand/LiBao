"""T6 tool_search 元工具 + 两段式 ACI 门控测试（纯单元 + 节点级闭环）。

覆盖：搜索命中/空提示/disabled 标注/降级全量目录、build_agent_tools 阈值门控与选中过滤、
节点级两段式流程（LLM 先 tool_search → 选中注入 → 再调具体工具）。
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.core.config import get_settings
from app.orchestration.context_builder import build_agent_tools
from app.orchestration.nodes.agent_execute import agent_execute_node
from app.orchestration.nodes.tool_execute import tool_execute_node
from app.tools.builtin import register_builtin_tools
from app.tools.builtin.tool_search import tool_search_handler
from app.tools.registry import ToolSpec, all_tools, register, unregister


@pytest.fixture(autouse=True)
def _cleanup():
    register_builtin_tools()
    for spec in [s for s in all_tools() if s.id.startswith("t_test")]:
        unregister(spec.id)
    yield
    for spec in [s for s in all_tools() if s.id.startswith("t_test")]:
        unregister(spec.id)


def _spec(sid: str, name: str, desc: str, enabled: bool = True) -> ToolSpec:
    return ToolSpec(id=sid, name=name, description=desc, enabled=enabled)


# ---- 元工具搜索 ----

async def test_search_matches_name_and_description():
    register(_spec("t_test_a", "stock_query", "股票查询工具"))
    register(_spec("t_test_b", "fetch_url", "抓取网页内容"))
    out = await tool_search_handler("股票")
    assert [m["name"] for m in out["matches"]] == ["stock_query"]
    out2 = await tool_search_handler("STOCK")  # 大小写不敏感
    assert [m["name"] for m in out2["matches"]] == ["stock_query"]
    out3 = await tool_search_handler("网页")
    assert [m["name"] for m in out3["matches"]] == ["fetch_url"]


async def test_search_empty_hint():
    register(_spec("t_test_a", "stock_query", "股票查询"))
    out = await tool_search_handler("宇宙无敌")
    assert out["matches"] == []
    assert "创建" in out["hint"]


async def test_search_disabled_marked():
    register(_spec("t_test_a", "stock_query", "股票查询", enabled=False))
    out = await tool_search_handler("股票")
    assert out["matches"][0]["enabled"] is False


async def test_search_fallback_full_catalog(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("search service down")

    monkeypatch.setattr("app.tools.builtin.tool_search._search_catalog", boom)
    out = await tool_search_handler("x")
    assert "matches" in out and len(out["matches"]) > 0
    # I4 降级：仅 id/name/description/enabled，不含 params_schema
    assert set(out["matches"][0].keys()) == {"id", "name", "description", "enabled"}


# ---- 两段式 ACI 门控 ----

def test_build_tools_under_limit_full_aci():
    aci = build_agent_tools(["tl_time_now", "tl_demo_notify"], [])
    assert [a["function"]["name"] for a in aci] == ["demo_notify", "time_now"]  # 按 id 排序


def test_build_tools_over_limit_two_stage(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "aci_full_limit", 1)  # 2 个启用工具 > 1 → 两段式
    aci = build_agent_tools(["tl_time_now", "tl_demo_notify"], ["time_now"])
    assert [a["function"]["name"] for a in aci] == ["tool_search", "time_now"]


def test_build_tools_selected_filtered(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "aci_full_limit", 1)
    register(_spec("t_test_disabled", "legacy", "旧工具", enabled=False))
    aci = build_agent_tools(
        ["tl_time_now", "tl_demo_notify", "t_test_disabled"],
        ["time_now", "nonexistent", "legacy"],  # 不存在 + disabled 均过滤
    )
    names = [a["function"]["name"] for a in aci]
    assert names == ["tool_search", "time_now"]


def test_build_tools_under_limit_ignores_selected(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "aci_full_limit", 30)  # 默认阈值
    aci = build_agent_tools(["tl_time_now"], ["time_now"])
    assert len(aci) == 1  # 全量模式不因 selected 变化


# ---- 节点级两段式闭环 ----

class CaptureModel:
    """mock LLM：第一轮调 tool_search，第二轮直接回答。记录 bind_tools 注入。"""

    def __init__(self) -> None:
        self.last_tools: list | None = None
        self._n = 0

    def bind_tools(self, tools, **kwargs):
        self.last_tools = tools
        return self

    async def ainvoke(self, messages):
        if self._n == 0:
            self._n = 1
            return AIMessage(
                content="", tool_calls=[{"name": "tool_search", "args": {"query": "当前时间"}, "id": "call_1", "type": "tool_call"}]
            )
        return AIMessage(content="现在是 12:00。")


async def test_two_stage_node_flow(monkeypatch):
    register_builtin_tools()
    s = get_settings()
    monkeypatch.setattr(s, "aci_full_limit", 1)  # 强制两段式
    model = CaptureModel()
    agent = {"model": "fake", "system_prompt": "p", "tools": ["tl_tool_search", "tl_time_now"], "max_steps": 5}

    # 第 1 轮：agent_execute → 只注入 tool_search（选中为空）
    state = {"agent_config": agent, "messages": [HumanMessage(content="现在几点")], "selected_tool_names": []}
    out1 = await agent_execute_node(state, {"configurable": {"model": model}})
    assert [a["function"]["name"] for a in out1["active_tools"]] == ["tool_search"]

    # 第 2 轮：tool_execute 执行 tool_search → 写入选中
    state2 = {**state, "messages": state["messages"] + out1["messages"]}
    out2 = await tool_execute_node(state2, {"configurable": {}})
    assert out2["selected_tool_names"] == ["time_now"]

    # 第 3 轮：agent_execute → 选中 ACI 注入（tool_search + time_now）
    state3 = {**state2, "messages": state2["messages"] + out2["messages"], "selected_tool_names": out2["selected_tool_names"]}
    out3 = await agent_execute_node(state3, {"configurable": {"model": model}})
    assert [a["function"]["name"] for a in out3["active_tools"]] == ["tool_search", "time_now"]
