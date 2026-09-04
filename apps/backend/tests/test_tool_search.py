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
    register(_spec("t_test_c", "web_page", "抓取网页内容"))  # 避开内置 tl_fetch_url 撞名（I7 遮蔽拒绝）
    out = await tool_search_handler("股票")
    assert [m["name"] for m in out["matches"]] == ["stock_query"]
    out2 = await tool_search_handler("STOCK")  # 大小写不敏感
    assert [m["name"] for m in out2["matches"]] == ["stock_query"]
    out3 = await tool_search_handler("网页")
    assert "web_page" in [m["name"] for m in out3["matches"]]  # 描述命中（目录含内置 fetch_url）


async def test_search_multi_keyword_query_matches_any_term_and_ranks_relevance():
    register(_spec("t_test_apify_a", "apify_actor", "网页抓取 crawler actor"))
    register(_spec("t_test_apify_b", "apify_misc", "Apify helper"))

    out = await tool_search_handler("apify 网页抓取爬虫 scrape crawler actor")

    names = [m["name"] for m in out["matches"]]
    assert names[0] == "apify_actor"
    assert "apify_misc" in names


async def test_search_blank_query_returns_no_matches():
    register(_spec("t_test_blank", "blank_query_target", "blank query target"))

    out = await tool_search_handler(" \t\n")

    assert out["matches"] == []


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


def test_build_tools_over_limit_injects_meta_kb_search(monkeypatch):
    """M6 收尾：kb_search 是 meta 工具，超限模式常驻注入（RAG 始终可见，无需 tool_search 发现）。"""
    s = get_settings()
    monkeypatch.setattr(s, "aci_full_limit", 1)
    aci = build_agent_tools(["tl_time_now", "tl_kb_search"], [])
    names = [a["function"]["name"] for a in aci]
    assert "tool_search" in names and "kb_search" in names  # 两个 meta 工具都常驻
    assert "time_now" not in names  # 非 meta 且未选中 → 不注入


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
                content="",
                tool_calls=[
                    {"name": "tool_search", "args": {"query": "当前时间"}, "id": "call_1", "type": "tool_call"}
                ],
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
    assert [a["function"]["name"] for a in model.last_tools] == ["tool_search"]

    # 第 2 轮：tool_execute 执行 tool_search → 写入选中
    state2 = {**state, "messages": state["messages"] + out1["messages"]}
    out2 = await tool_execute_node(state2, {"configurable": {}})
    assert out2["selected_tool_names"] == ["time_now"]

    # 第 3 轮：agent_execute → 选中 ACI 注入（tool_search + time_now）
    state3 = {
        **state2,
        "messages": state2["messages"] + out2["messages"],
        "selected_tool_names": out2["selected_tool_names"],
    }
    await agent_execute_node(state3, {"configurable": {"model": model}})
    assert [a["function"]["name"] for a in model.last_tools] == ["tool_search", "time_now"]


async def test_two_stage_meta_tool_without_agent_optin(monkeypatch):
    # I7：超限 agent 未勾选 tool_search → ACI 强制注入 + 执行守卫放行（平台元工具语义）
    s = get_settings()
    monkeypatch.setattr(s, "aci_full_limit", 0)  # 1 个启用工具 > 0 → 超限
    agent = {"model": "fake", "system_prompt": "p", "tools": ["tl_time_now"], "max_steps": 5}
    model = CaptureModel()
    state = {"agent_config": agent, "messages": [HumanMessage(content="现在几点")], "selected_tool_names": []}
    out1 = await agent_execute_node(state, {"configurable": {"model": model}})
    assert [a["function"]["name"] for a in model.last_tools] == ["tool_search"]  # 强制注入
    state2 = {**state, "messages": state["messages"] + out1["messages"]}
    out2 = await tool_execute_node(state2, {"configurable": {}})  # 执行不被 agent_can_use gate
    assert out2["selected_tool_names"] == ["time_now"]


async def test_search_empty_result_clears_selection(monkeypatch):
    # M1：空结果（带 hint）→ 清空旧选中，防残留陈旧注入
    s = get_settings()
    monkeypatch.setattr(s, "aci_full_limit", 1)
    agent = {"model": "fake", "system_prompt": "p", "tools": ["tl_tool_search", "tl_time_now"], "max_steps": 5}
    msg = AIMessage(
        content="",
        tool_calls=[{"name": "tool_search", "args": {"query": "zzz不存在的查询"}, "id": "c1", "type": "tool_call"}],
    )
    state = {
        "agent_config": agent,
        "messages": [HumanMessage(content="x"), msg],
        "selected_tool_names": ["time_now"],  # 旧选中
    }
    out = await tool_execute_node(state, {"configurable": {}})
    assert out["selected_tool_names"] == []  # 空结果清空


async def test_multiple_search_calls_merged(monkeypatch):
    # M1：一轮内多次 tool_search → 结果合并（去重保序）
    s = get_settings()
    monkeypatch.setattr(s, "aci_full_limit", 1)
    agent = {"model": "fake", "system_prompt": "p", "tools": ["tl_tool_search", "tl_time_now"], "max_steps": 5}
    msg = AIMessage(
        content="",
        tool_calls=[
            {"name": "tool_search", "args": {"query": "当前时间"}, "id": "c1", "type": "tool_call"},
            {"name": "tool_search", "args": {"query": "通知"}, "id": "c2", "type": "tool_call"},
        ],
    )
    state = {"agent_config": agent, "messages": [HumanMessage(content="x"), msg], "selected_tool_names": []}
    out = await tool_execute_node(state, {"configurable": {}})
    assert out["selected_tool_names"] == ["time_now", "demo_notify"]
