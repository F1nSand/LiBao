"""tool_search 元工具（docs 01 §7.1.1 A2）。

模型侧只暴露"搜索工具目录"一个接口（不塞全量工具定义）；返回匹配工具的
名称 + 路由描述（何时用/何时别用），**不含全量 ACI 参数 schema**。
I4 降级：空 → 提示创建；检索挂 → 降级全量目录（仅名称+路由描述）；disabled → 标注"未启用"。
"""
from __future__ import annotations

from typing import Any

from app.tools.registry import all_tools


def _search_catalog(catalog: list, q: str) -> list[dict]:
    """匹配逻辑（独立函数：I4 降级只兜匹配失败，不兜目录获取）。"""
    return [
        {
            "id": spec.id,
            "name": spec.name,
            "description": spec.description,
            "enabled": spec.enabled,
            "mcp_source": spec.mcp_source,
        }
        for spec in catalog
        if q in spec.name.lower() or q in (spec.description or "").lower()
    ]


async def tool_search_handler(query: str) -> dict[str, Any]:
    """按名称/描述搜索（不区分大小写），按 id 排序。"""
    q = query.lower()
    catalog = list(all_tools())
    try:
        matches = _search_catalog(catalog, q)
        if not matches:
            return {"matches": [], "hint": "无匹配工具，可在工具管理页创建"}
        matches.sort(key=lambda m: m["id"])
        return {"matches": matches}
    except Exception:  # noqa: BLE001  I4：检索逻辑挂 → 降级全量目录（仅名称+路由描述），不阻塞模型
        fallback = [
            {"id": s.id, "name": s.name, "description": s.description, "enabled": s.enabled} for s in catalog
        ]
        fallback.sort(key=lambda m: m["id"])
        return {"matches": fallback, "hint": None}
