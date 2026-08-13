"""上下文构建器（docs 01 §4.1 context_builder）。

三段式：① system_prompt 静态置顶 ② 工具 ACI 静态（bind_tools，函数定义不进消息正文）③ 动态内容追加尾部。
前缀稳定性铁律：系统提示词与 ACI 一旦确定不改；动态内容（状态栏等）永远追加末尾。
compute_prefix_hash 与 app/seed._prefix_hash 同一算法（字节稳定）。
"""
from __future__ import annotations

import hashlib
import json

from langchain_core.messages import BaseMessage, SystemMessage

from app.orchestration.state_schema import AgentState
from app.tools.registry import acis


def compute_prefix_hash(model: str, system_prompt: str, tool_ids: list[str]) -> str:
    canonical = json.dumps(
        {"model": model, "system_prompt": system_prompt, "tools": sorted(tool_ids)},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def static_prefix_aci() -> list[dict]:
    """全部工具 ACI（静态前缀之②），按 id 排序。"""
    return acis()


def acis_for_tools(tool_ids: list[str]) -> list[dict]:
    """agent_config.tools（工具 id 列表）→ 启用的 ACI，按 id 排序（前缀稳定）。"""
    from app.tools.registry import get

    specs = [s for tid in tool_ids if (s := get(tid)) is not None and s.enabled]
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
