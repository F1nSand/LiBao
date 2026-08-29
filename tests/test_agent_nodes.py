"""agent_execute 节点错误边界测试。"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.core.errors import LLMTransportError
from app.orchestration.nodes.agent_execute import agent_execute_node


class _TransportFailureModel:
    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        raise RuntimeError("peer closed connection without sending complete message body")


@pytest.mark.asyncio
async def test_agent_execute_normalizes_transport_error_without_raw_payload():
    state = {
        "agent_config": {"model": "glm-5.3-flash", "tools": [], "system_prompt": "", "max_steps": 5},
        "messages": [HumanMessage(content="hello")],
        "flags": {"steps": 0},
        "totals": {},
        "run_logs": [],
    }

    with pytest.raises(LLMTransportError) as caught:
        await agent_execute_node(state, {"configurable": {"model": _TransportFailureModel()}})

    assert caught.value.details["model"] == "glm-5.3-flash"
    assert "peer closed" not in str(caught.value.details)
