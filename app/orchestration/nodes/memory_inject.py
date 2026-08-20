"""memory_inject 节点（docs 01 §8.2 / docs 03 §3.1 记忆注入）。

每轮从长期记忆取 importance top-N 卡片写入 state.memory_refs，build_context 渲染为尾部块。
硬性不变量：user_id 缺失 / sessionmaker 桥未设 / 查询失败 → memory_refs=[] 静默跳过，
注入永不击穿对话（同 tool_search I4 降级语义）。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from app.core.config import get_settings
from app.orchestration.state_schema import AgentState
from app.storage.db import get_sessionmaker
from app.storage.repositories.memory import MemoryRepository


def _card_ref(card: Any, max_chars: int) -> dict[str, Any]:
    """卡片 → 注入引用（title/类型 + 截断的 content 文本）。"""
    return {
        "id": str(card.id),
        "title": card.title or card.card_type,
        "card_type": card.card_type,
        "content_text": json.dumps(card.content, ensure_ascii=False)[:max_chars],
        "importance": card.importance,
    }


async def memory_inject_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    user_id = state.get("user_id")
    if not user_id:
        return {"memory_refs": []}  # 静默跳过
    sessionmaker = get_sessionmaker()
    if sessionmaker is None:
        return {"memory_refs": []}  # 桥未设（测试/独立调用）→ 静默跳过
    trace_id = (config or {}).get("configurable", {}).get("trace_id")
    start = time.perf_counter()
    try:
        agent_cfg = state.get("agent_config", {}) or {}
        ws_id = agent_cfg.get("workspace_id")
        async with sessionmaker() as db:
            cards = await MemoryRepository(db).list_cards(
                uuid.UUID(user_id),
                limit=get_settings().memory_inject_limit,
                workspace_id=uuid.UUID(ws_id) if ws_id else None,
            )
            refs = [_card_ref(c, get_settings().memory_card_max_chars) for c in cards]
    except Exception:  # noqa: BLE001  注入故障不击穿对话
        return {"memory_refs": []}
    duration_ms = int((time.perf_counter() - start) * 1000)
    return {
        "memory_refs": refs,
        "run_logs": (state.get("run_logs") or [])
        + [
            {
                "node": "memory_inject",
                "type": "memory",
                "trace_id": trace_id,
                "input": {"user_id": user_id, "inject_limit": get_settings().memory_inject_limit},
                "output": {"card_ids": [r["id"] for r in refs], "count": len(refs)},
                "duration_ms": duration_ms,
                "status": "ok",
            }
        ],
    }
