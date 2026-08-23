"""主动记忆工具（P4）：remember_memory / recall_memory / forget_memory。

scope：global（长期记忆卡片 + RAG 向量，source=tool）| project（工作区 .agent/memory/*.md）。
auto 推断：remember 有工作区 → project，否则 global；recall 两者合并（标注 scope）。
与自动提取分支同源（MemoryRepository / memory_extract._write_project_md）；
失败返回 dict 不抛（不击穿对话，与全部内置工具同约定）。
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any

from app.services.memory_extract import _parse_project_md, _slugify, _write_project_md
from app.storage.repositories.memory import MemoryRepository
from app.tools.context import get_tool_user_id, get_tool_workspace_id, get_tool_workspace_root

logger = logging.getLogger(__name__)

_PROJECT_MEMORY_DIR = ".agent/memory"


def _resolve_scope(scope: str | None, workspace_root: str | None) -> str:
    """auto → 有工作区上下文 project，否则 global。"""
    scope = (scope or "auto").strip().lower()
    if scope in ("global", "project"):
        return scope
    return "project" if workspace_root else "global"


def _clamp_importance(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


async def remember_memory_handler(
    content: str, scope: str | None = None, title: str | None = None,
    tags: list[str] | None = None, importance: float | None = None,
) -> dict[str, Any]:
    """写入一条长期记忆（用户显式「记一下」或值得长期保留的事实/决策）。"""
    user_id = get_tool_user_id()
    if not user_id:
        return {"error": "无法确定用户上下文"}
    ws_root = get_tool_workspace_root()
    if _resolve_scope(scope, ws_root) == "project":
        item = {
            "scope": "project",
            "title": title or "",
            "content": content,
            "importance": _clamp_importance(importance if importance is not None else 0.5),
            "topic_key": _slugify(title or content[:20]),
            "type": "note",
            "tags": [str(t) for t in (tags or [])],
        }
        try:
            await _write_project_md(ws_root, item, None)
        except Exception as exc:  # noqa: BLE001  写文件失败返回错误结果（不抛）
            logger.warning("remember_memory project write failed: %s", exc)
            return {"error": f"项目记忆写入失败: {str(exc)[:200]}"}
        return {"ok": True, "scope": "project", "path": f"{_PROJECT_MEMORY_DIR}/{item['topic_key']}.md"}
    # global → 卡片 + 向量（repository 内同步）
    try:
        card = await MemoryRepository().create_card(
            user_id=uuid.UUID(user_id),
            card_type="note",
            content={"text": content.strip()},
            title=title or None,
            tags=[str(t) for t in (tags or [])] or None,
            importance=_clamp_importance(importance if importance is not None else 0.5),
            source="tool",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("remember_memory global write failed: %s", exc)
        return {"error": f"记忆写入失败: {str(exc)[:200]}"}
    return {"ok": True, "scope": "global", "card_id": str(card.id), "title": card.title}


async def recall_memory_handler(
    query: str, scope: str | None = None, limit: int = 5,
) -> dict[str, Any]:
    """检索长期记忆：global = RAG 语义检索卡片；project = 工作区 md 关键词扫描。"""
    user_id = get_tool_user_id()
    if not user_id:
        return {"error": "无法确定用户上下文"}
    ws_root = get_tool_workspace_root()
    ws_id = get_tool_workspace_id()
    limit = max(1, min(int(limit or 5), 20))
    out: dict[str, Any] = {"query": query, "hits": []}
    try:
        if _resolve_scope(scope, ws_root) == "project":
            out["hits"] = _scan_project_memory(ws_root, query, limit)
        else:
            cards = await MemoryRepository().semantic_search(
                uuid.UUID(user_id), query, workspace_id=uuid.UUID(ws_id) if ws_id else None, limit=limit
            )
            out["hits"] = [
                {
                    "scope": "global",
                    "card_id": str(c.id),
                    "title": c.title or c.card_type,
                    "content": (c.content or {}).get("text", ""),
                    "importance": c.importance,
                }
                for c in cards
            ]
    except Exception as exc:  # noqa: BLE001  检索故障返回错误结果（不抛）
        logger.warning("recall_memory failed: %s", exc)
        return {"error": f"记忆检索失败: {str(exc)[:200]}"}
    return out


def _scan_project_memory(workspace_root: str, query: str, limit: int) -> list[dict[str, Any]]:
    """项目记忆关键词扫描：匹配标题/正文 → 摘要片段（含 query 的 ±60 字窗口）。"""
    memory_dir = Path(workspace_root) / _PROJECT_MEMORY_DIR
    if not memory_dir.is_dir():
        return []
    needle = query.strip().lower()
    hits: list[dict[str, Any]] = []
    for md in sorted(memory_dir.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if needle and needle not in text.lower():
            continue
        title, body = "md 文件", text
        parsed = _parse_project_md(text)
        if parsed is not None:
            meta, body = parsed
            title = str(meta.get("title") or md.stem)
        snippet = _snippet(body, needle, width=60) if needle else body[:120]
        hits.append(
            {
                "scope": "project",
                "path": f"{_PROJECT_MEMORY_DIR}/{md.name}",
                "title": title,
                "snippet": snippet,
            }
        )
        if len(hits) >= limit:
            break
    return hits


def _snippet(text: str, needle: str, width: int = 60) -> str:
    """含 query 的上下文片段（定位首个匹配处 ±width 字）。"""
    idx = text.lower().find(needle)
    if idx < 0:
        return text[: width * 2]
    start = max(0, idx - width)
    end = min(len(text), idx + len(needle) + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


async def forget_memory_handler(query: str, scope: str | None = None) -> dict[str, Any]:
    """删除/归档一条长期记忆：global 按标题匹配软删卡片（+删向量）；project 归档 md 到 .trash。"""
    user_id = get_tool_user_id()
    if not user_id:
        return {"error": "无法确定用户上下文"}
    needle = (query or "").strip()
    # review C2：空/空白 query 会匹配全部（"" in 任意字符串 恒真）→ 防全量误删
    if not needle:
        return {"error": "query 不能为空：请给出要删除记忆的标题或关键词"}
    ws_root = get_tool_workspace_root()
    try:
        if _resolve_scope(scope, ws_root) == "project":
            removed = _archive_project_memory(ws_root, needle)
            return {"ok": True, "scope": "project", "archived": removed}
        repo = MemoryRepository()
        cards = await repo.table.list(filter_fn=lambda c: c.user_id == uuid.UUID(user_id) and c.deleted_at is None)
        matches = [c for c in cards if needle.lower() in (c.title or "").lower()
                   or needle.lower() in (c.content or {}).get("text", "").lower()]
        if len(matches) > 10:
            # 匹配过宽（含糊 query 会误删大量记忆）→ 要求更精确
            return {"error": f"匹配到 {len(matches)} 条记忆，query 过于宽泛：请给出更精确的标题/关键词"}
        for c in matches:
            await repo.soft_delete(c)
        return {"ok": True, "scope": "global", "deleted": len(matches), "card_ids": [str(c.id) for c in matches]}
    except Exception as exc:  # noqa: BLE001
        logger.warning("forget_memory failed: %s", exc)
        return {"error": f"记忆删除失败: {str(exc)[:200]}"}


def _archive_project_memory(workspace_root: str, query: str) -> int:
    """项目记忆归档：匹配标题/文件名 → 移入 .trash/（不硬删，可恢复）。

    同名冲突（不同 query 先后匹配同一文件/重复归档）→ 追加时间戳后缀防覆盖。
    """
    memory_dir = Path(workspace_root) / _PROJECT_MEMORY_DIR
    if not memory_dir.is_dir():
        return 0
    trash = memory_dir / ".trash"
    trash.mkdir(exist_ok=True)
    needle = query.strip().lower()
    removed = 0
    for md in sorted(memory_dir.glob("*.md")):
        if needle and needle not in md.stem.lower():
            parsed = _parse_project_md(md.read_text(encoding="utf-8", errors="ignore"))
            if parsed is None or needle not in str(parsed[0].get("title", "")).lower():
                continue
        try:
            target = trash / md.name
            if target.exists():  # review C4：同名已归档 → 时间戳后缀防覆盖
                target = trash / f"{md.stem}.{int(time.time())}{md.suffix}"
            md.rename(target)
            removed += 1
        except OSError as exc:  # noqa: BLE001  单文件归档失败不影响其余
            logger.warning("archive %s failed: %s", md.name, exc)
    return removed
