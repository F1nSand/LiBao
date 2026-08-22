"""通用分页（docs 03 §5 契约：Paged<T> = {items, total, page, page_size}）。"""

from __future__ import annotations

from typing import Any


def paged(items: list[Any], total: int, page: int, page_size: int) -> dict[str, Any]:
    return {"items": items, "total": total, "page": page, "page_size": page_size}
