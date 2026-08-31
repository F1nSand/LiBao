"""memory_inject 节点（《02》后端设计 §8.2 / 《02》接口契约 §3.1 记忆注入）。

每轮从长期记忆取 top-N 卡片写入 state.memory_refs，build_context 渲染为尾部块。
P2 起为 RAG 检索：query = 最近 user 消息，语义检索（memory_vectors.lance）；
embedding/向量表故障或 query 空 → 回退 importance 排序（原行为保底）。
硬性不变量：user_id 缺失 / 查询失败 → memory_refs=[] 静默跳过，注入永不击穿对话。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig

from app.core.config import get_settings
from app.orchestration.state_schema import AgentState
from app.orchestration.stream_core import message_text
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


def _last_user_text(messages: list[Any]) -> str:
    """最近一条 user 消息文本 → RAG 检索 query（无则空 → 回退 importance）。"""
    for m in reversed(messages):
        role = getattr(m, "type", "") or (m.get("role") if isinstance(m, dict) else "")
        if role in ("user", "human"):
            return message_text(m.get("content", "") if isinstance(m, dict) else getattr(m, "content", ""))
    return ""


async def memory_inject_node(state: AgentState, config: Optional[RunnableConfig] = None) -> dict[str, Any]:  # noqa: UP045  LangGraph 需 Optional 形式
    user_id = state.get("user_id")
    if not user_id:
        return {"memory_refs": []}  # 静默跳过
    trace_id = (config or {}).get("configurable", {}).get("trace_id")
    start = time.perf_counter()
    try:
        agent_cfg = state.get("agent_config", {}) or {}
        ws_id = agent_cfg.get("workspace_id")
        query = _last_user_text(state.get("messages", []) or [])
        # P2：语义检索注入（query 空/检索故障 → 内部回退 importance 排序）
        cards = await MemoryRepository().semantic_search(
            uuid.UUID(user_id),
            query,
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
