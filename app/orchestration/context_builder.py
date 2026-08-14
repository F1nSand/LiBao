"""上下文构建器（docs 01 §4.1 context_builder）。

三段式：① system_prompt 静态置顶 ② 工具 ACI 静态（bind_tools，函数定义不进消息正文）③ 动态内容追加尾部。
前缀稳定性铁律：系统提示词与 ACI 一旦确定不改；动态内容（状态栏等）永远追加末尾。
"""
from __future__ import annotations

from langchain_core.messages import BaseMessage, SystemMessage

from app.core.prefix import compute_prefix_hash  # noqa: F401  重导出供 seed/测试复用
from app.orchestration.state_schema import AgentState
from app.tools.registry import acis, agent_can_use, get


def static_prefix_aci() -> list[dict]:
    """全部工具 ACI（静态前缀之②），按 id 排序。"""
    return acis()


def acis_for_tools(tool_ids: list[str]) -> list[dict]:
    """agent_config.tools（工具 id 列表）→ 启用的 ACI，按 id 排序（前缀稳定）。

    授权谓词与 tool_execute 执行守卫共用 agent_can_use（同一不变量）。
    """
    specs = [s for tid in tool_ids if (s := get(tid)) is not None and agent_can_use(s, tool_ids)]
    return [s.aci() for s in sorted(specs, key=lambda s: s.id)]


def build_context(state: AgentState) -> list[BaseMessage]:
    """组装进模型的完整消息列表：SystemMessage(静态) + 历史 + 状态栏(尾部动态)。"""
    agent = state.get("agent_config", {})
    system_prompt = agent.get("system_prompt", "")

    system = SystemMessage(content=system_prompt)
    history: list[BaseMessage] = list(state.get("messages", []))

    # 状态栏（代码维护，append-only 尾部，docs 01 §4.3）
    status_bar = state.get("flags", {}).get("status_bar")
    if status_bar:
        history.append(SystemMessage(content=status_bar))

    return [system] + history
