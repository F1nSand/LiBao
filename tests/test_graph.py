"""编排层测试（T9 判据）：build_graph 编译 + mock LLM 走通一次工具调用 + 静态前缀字节稳定。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.orchestration.context_builder import acis_for_tools, build_context, compute_prefix_hash
from app.orchestration.graph import build_graph
from app.tools.builtin import register_builtin_tools


class FakeChatModel:
    """最小可注入模型：bind_tools 记录 ACI；ainvoke 按序返回预设响应。"""

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


def _agent_config() -> dict:
    return {
        "model": "fake-model",
        "system_prompt": "你是时间助手，用 time_now 工具获取当前时间后回答。",
        "tools": ["tl_time_now"],
        "max_steps": 10,
    }


def test_build_graph_compiles():
    graph = build_graph()
    assert graph is not None


async def test_mock_llm_single_tool_call_roundtrip():
    register_builtin_tools()
    fake = FakeChatModel(
        [
            AIMessage(content="", tool_calls=[{"name": "time_now", "args": {}, "id": "call_1", "type": "tool_call"}]),
            AIMessage(content="现在是 2026 年 8 月 13 日 21:00（Asia/Shanghai）。"),
        ]
    )
    graph = build_graph()
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="现在几点？")], "agent_config": _agent_config()},
        {"configurable": {"model": fake}},
    )

    # 模型侧确实拿到了工具 ACI
    assert fake.bind_count == 2
    assert fake.last_tools and fake.last_tools[0]["function"]["name"] == "time_now"

    # 最终消息
    fm = result["final_message"]
    assert "现在是 2026 年" in fm["content"]
    assert fm["role"] == "assistant"
    assert len(fm["tool_calls"]) == 1
    tc = fm["tool_calls"][0]
    assert tc["tool_name"] == "time_now" and tc["ok"] is True and tc["position"] == 0
    assert tc["output"]["tz"] == "Asia/Shanghai"

    # 状态机收敛
    assert result["flags"]["status"] == "done"
    assert result["flags"]["steps"] == 2  # 两次 agent_execute

    # 消息流：user → assistant(tool_call) → tool → assistant(final)
    roles = [m.type for m in result["messages"]]
    assert roles == ["human", "ai", "tool", "ai"]


def test_static_prefix_byte_stable():
    register_builtin_tools()
    acis1 = acis_for_tools(["tl_time_now"])
    assert acis1 == acis_for_tools(["tl_time_now"])  # 同输入字节稳定

    ctx_a = build_context({"agent_config": _agent_config(), "messages": [HumanMessage(content="a")]})
    ctx_b = build_context({"agent_config": _agent_config(), "messages": [HumanMessage(content="不同历史")]})
    assert ctx_a[0].content == ctx_b[0].content  # 静态 system 不随历史变

    h1 = compute_prefix_hash("m", "p", ["tl_time_now"])
    assert h1 == compute_prefix_hash("m", "p", ["tl_time_now"])
    assert h1 != compute_prefix_hash("m", "p2", ["tl_time_now"])
