"""单通用 Agent 有效工具集：seed 精选 ∪ 本组织已启用工具（MCP/自定义启用即对通用助手开放）。

修复验证：build_initial_state 透传 enabled_tool_ids → agent_config.tools 并集 → ACI 与执行守卫
（同源 agent_can_use）都包含启用但不在 seed 列表的工具。
"""
from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage

from app.orchestration.context_builder import build_agent_tools
from app.orchestration.graph import build_graph
from app.orchestration.stream_core import build_initial_state
from app.tools.builtin import register_builtin_tools
from app.tools.registry import ToolSpec, register, unregister


def _agent() -> SimpleNamespace:
    return SimpleNamespace(
        name="通用助手",
        model="fake",
        system_prompt="你是助手。",
        tools=["tl_time_now"],  # seed 精选：不含待验证的启用工具
        max_steps=5,
        org_id="org-1",
    )


def test_initial_state_unions_enabled_tools():
    initial = build_initial_state(_agent(), "hi", enabled_tool_ids=["mc_server_x_tool"])
    tools_list = initial["agent_config"]["tools"]
    tools = set(tools_list)
    assert "mc_server_x_tool" in tools  # 启用工具并入
    assert "tl_time_now" in tools  # seed 保留
    assert tools_list == sorted(tools_list)  # 确定性排序（前缀稳定）


async def test_enabled_non_seed_tool_reaches_aci():
    register_builtin_tools()
    fake = ToolSpec(
        id="mc_server_x_tool", name="x_tool", description="模拟 MCP 启用工具",
        params_schema={"type": "object", "properties": {}, "required": []},
        enabled=True,
    )
    register(fake)
    try:
        initial = build_initial_state(_agent(), "hi", enabled_tool_ids=["mc_server_x_tool"])
        aci_names = [a["function"]["name"] for a in build_agent_tools(initial["agent_config"]["tools"])]
        assert "x_tool" in aci_names  # 修复后：启用即进 ACI
    finally:
        unregister(fake.id)


async def test_graph_executes_enabled_non_seed_tool():
    """图级：模型调用启用但非 seed 的工具 → tool_execute 守卫放行（agent_can_use 同源）。"""
    register_builtin_tools()
    executed = []

    async def fake_handler(echo: str = "") -> str:
        executed.append(echo)
        return f"echo:{echo}"

    fake = ToolSpec(
        id="mc_server_x_tool", name="x_tool", description="模拟 MCP 启用工具",
        params_schema={"type": "object", "properties": {"echo": {"type": "string"}}, "required": []},
        enabled=True,
        handler=fake_handler,
    )
    register(fake)

    class FakeChatModel:
        def __init__(self) -> None:
            self._n = 0

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            self._n += 1
            if self._n == 1:
                return AIMessage(
                    content="",
                    tool_calls=[{"name": "x_tool", "args": {"echo": "hi"}, "id": "call_x", "type": "tool_call"}],
                )
            return AIMessage(content="完成。")

    try:
        graph = build_graph()
        initial = build_initial_state(_agent(), "用 x_tool", enabled_tool_ids=["mc_server_x_tool"])
        result = await graph.ainvoke(
            initial, {"configurable": {"model": FakeChatModel(), "thread_id": "thr-tool-scope"}}
        )
        assert executed == ["hi"], f"启用但非 seed 的工具未被执行守卫放行: {executed}"
        assert "完成。" in result["final_message"]["content"]
    finally:
        unregister(fake.id)
