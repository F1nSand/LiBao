"""工具目录的无依赖关键词匹配。"""

from __future__ import annotations

import re

_QUERY_SEPARATOR = re.compile(r"[\s,，;；、|/]+")


def tokenize_tool_query(query: str) -> list[str]:
    """将自然语言关键词串规范化、去重，并保留首次出现顺序。"""
    normalized = query.strip().lower()
    if not normalized:
        return []
    return list(dict.fromkeys(part for part in _QUERY_SEPARATOR.split(normalized) if part))


def tool_match_score(
    name: str, description: str | None, query: str
) -> tuple[int, int, int, int] | None:
    """返回匹配相关度；任一关键词都未命中时返回 None。"""
    normalized = query.strip().lower()
    tokens = tokenize_tool_query(query)
    if not tokens:
        return None

    name_text = name.lower()
    description_text = (description or "").lower()
    name_hits = sum(token in name_text for token in tokens)
    total_hits = sum(token in name_text or token in description_text for token in tokens)
    if total_hits == 0:
        return None
    return (
        int(normalized in name_text),
        int(normalized in description_text),
        name_hits,
        total_hits,
    )
