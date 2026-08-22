"""kb_search 内置工具（docs 01 §9.2 Agentic RAG 预留：检索封装为工具，LLM 自主决定搜什么）。

五层约束下工具层→存储层合法：经 FileStore + KbRepository.hybrid_search（RRF 单一来源）。
本地单机化：org 上下文缺失 → 恒用默认 org（折叠）。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.storage.constants import DEFAULT_ORG_ID
from app.storage.file.store import get_store
from app.storage.repositories.kb import KbRepository
from app.tools.context import get_tool_org


async def kb_search_handler(
    query: str,
    collection_ids: list[str] | None = None,
    top_k: int = 5,
    semantic: bool = True,
    bm25: bool = True,
) -> dict[str, Any]:
    org_id = get_tool_org() or str(DEFAULT_ORG_ID)  # 折叠：无上下文时用默认 org
    store = get_store()
    if store is None:
        return {"error": "知识库服务不可用"}
    try:
        coll_ids = [uuid.UUID(c) for c in (collection_ids or [])]
        hits = await KbRepository().hybrid_search(
            uuid.UUID(org_id), coll_ids, query, top_k, {"semantic": semantic, "bm25": bm25}
        )
    except Exception as exc:  # noqa: BLE001  检索故障不击穿工具调用
        return {"error": f"检索失败: {str(exc)[:300]}"}
    return {"results": hits, "count": len(hits)}
