"""记忆卡片向量索引（主动记忆 RAG，docs 01 §8.2/§8.3）。

LanceDB 独立库 `.agent/memory_vectors.lance`（与 kb/vectors.lance 分离，规避 kb 集合遍历），
单表 memory_vectors：card_id 主键 / user_id / workspace_id(""=全局) / importance / content / vector(1024)。

同步点：MemoryRepository.create_card / add_version / soft_delete（本模块 upsert/delete）。
RAG 是增强不是依赖：写入失败静默降级（卡片/版本照常落盘），注入侧检索失败回退 importance 排序。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.storage.file.store import get_store

logger = logging.getLogger(__name__)

_lance_db: Any = None
_lance_table: Any = None


def _card_text(card: Any) -> str:
    """卡片 content → 索引/检索文本（note 取 text；json_card 序列化）。"""
    content = card.content or {}
    if isinstance(content, dict) and "text" in content:
        return str(content["text"])
    return json.dumps(content, ensure_ascii=False)


def _get_table() -> Any:
    """.agent/memory_vectors.lance 单表（首次惰性建表；模块级缓存，测试用 reset_memory_lance）。"""
    global _lance_db, _lance_table
    if _lance_table is not None:
        return _lance_table
    import lancedb
    import pyarrow as pa

    store = get_store()
    if _lance_db is None:
        _lance_db = lancedb.connect(str(store.root / "memory_vectors.lance"))
    name = "memory_vectors"
    if name in _lance_db.table_names():
        _lance_table = _lance_db.open_table(name)
    else:
        schema = pa.schema(
            [
                pa.field("card_id", pa.string()),
                pa.field("user_id", pa.string()),
                pa.field("workspace_id", pa.string()),
                pa.field("importance", pa.float32()),
                pa.field("content", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), 1024)),
            ]
        )
        _lance_table = _lance_db.create_table(name, schema=schema)
    return _lance_table


def reset_memory_lance() -> None:
    """重置模块级 LanceDB 缓存（测试隔离）。"""
    global _lance_db, _lance_table
    _lance_db = None
    _lance_table = None


async def upsert_card(card: Any, vector: list[float]) -> None:
    """写入/更新卡片向量（merge_insert 同主键 upsert 防重复行；workspace_id None → "" 全局）。"""
    if not vector:
        return
    import numpy as np

    _get_table().merge_insert("card_id").when_matched_update_all().when_not_matched_insert_all().execute(
        [
            {
                "card_id": str(card.id),
                "user_id": str(card.user_id),
                "workspace_id": str(card.workspace_id) if card.workspace_id else "",
                "importance": float(card.importance or 0.0),
                "content": _card_text(card),
                "vector": np.asarray(vector, dtype=np.float32).tolist(),
            }
        ]
    )


async def delete_card(card_id: Any) -> None:
    """软删同步删向量（表不存在/空表容错）。"""
    try:
        _get_table().delete(f"card_id = '{card_id}'")
    except Exception as exc:  # noqa: BLE001
        logger.debug("memory vector delete skip: %s", exc)


async def search(
    user_id: str, vector: list[float], *, workspace_id: str | None = None, limit: int = 5
) -> list[tuple[str, float]]:
    """余弦检索 top-N → [(card_id, distance)] 升序。

    作用域与 list_cards 同语义（M7-B）：普通会话 = 全局（workspace_id=""）；
    工作区会话 = 项目 ∪ 全局（IN ('<ws>', '')）。
    """
    table = _get_table()
    if table.count_rows() == 0:
        return []
    if workspace_id:
        where = f"user_id = '{user_id}' AND workspace_id IN ('{workspace_id}', '')"
    else:
        where = f"user_id = '{user_id}' AND workspace_id = ''"
    hits = table.search(vector).metric("cosine").where(where).limit(limit).to_list()
    return [(h["card_id"], float(h["_distance"])) for h in hits]
