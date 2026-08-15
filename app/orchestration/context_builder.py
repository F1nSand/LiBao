"""上下文构建器（docs 01 §4.1 context_builder）。

三段式：① system_prompt 静态置顶 ② 工具 ACI 静态（bind_tools，函数定义不进消息正文）③ 动态内容追加尾部。
前缀稳定性铁律：系统提示词与 ACI 一旦确定不改；动态内容（状态栏等）永远追加末尾。
"""
from __future__ import annotations

from langchain_core.messages import BaseMessage, SystemMessage

from app.core.config import get_settings
from app.core.prefix import compute_prefix_hash  # noqa: F401  重导出供 seed/测试复用
from app.orchestration.state_schema import AgentState
from app.tools.registry import ToolSpec, acis, agent_can_use, get, get_by_name


def static_prefix_aci() -> list[dict]:
    """全部工具 ACI（静态前缀之②），按 id 排序。"""
    return acis()


def _authorized_specs(tool_ids: list[str], id_set: set[str]) -> list[ToolSpec]:
    """agent 启用集 → 授权 spec（与 tool_execute 执行守卫共用 agent_can_use 单一不变量）。"""
    return [s for tid in tool_ids if (s := get(tid)) is not None and agent_can_use(s, id_set)]


def acis_for_tools(tool_ids: list[str]) -> list[dict]:
    """agent_config.tools（工具 id 列表）→ 启用的 ACI，按 id 排序（前缀稳定）。"""
    specs = _authorized_specs(tool_ids, set(tool_ids))
    return [s.aci() for s in sorted(specs, key=lambda s: s.id)]


def build_agent_tools(tool_ids: list[str], selected_names: list[str] | None = None) -> list[dict]:
    """工具 ACI 注入（M2.5 两段式门控，docs 01 §7.1.1 A2）。

    启用工具数 ≤ aci_full_limit → 维持现状全量 ACI（现有场景零行为变化）；
    超过 → tool_search 常驻 + 上次搜索选中的工具 ACI（渐进式披露），选中按授权过滤。
    """
    id_set = set(tool_ids)
    specs = _authorized_specs(tool_ids, id_set)
    if len(specs) <= get_settings().aci_full_limit:
        return [s.aci() for s in sorted(specs, key=lambda s: s.id)]
    tool_search = get("tl_tool_search")
    chosen = [
        s
        for n in (selected_names or [])
        if (s := get_by_name(n)) is not None
        and agent_can_use(s, id_set)
        and not s.meta
    ]
    aci = [tool_search.aci()] if tool_search is not None and tool_search.enabled else []
    return aci + [s.aci() for s in sorted(chosen, key=lambda s: s.id)]


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
