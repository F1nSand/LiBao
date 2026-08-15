"""tool_search 元工具（docs 01 §7.1.1 A2）。

模型侧只暴露"搜索工具目录"一个接口（不塞全量工具定义）；返回匹配工具的
名称 + 路由描述（何时用/何时别用），**不含全量 ACI 参数 schema**。
I4 降级：空 → 提示创建；检索挂 → 降级全量目录（仅名称+路由描述）；disabled → 标注"未启用"。
"""
from __future__ import annotations

from typing import Any

from app.tools.registry import all_tools

_SELECT_LIMIT = 5  # 两段式选中注入上限（docs 01 §7.1.1：选中 1-2 个，防上下文爆炸）


def _catalog_projection(catalog: list, include_mcp_source: bool) -> list[dict]:
    """spec → 目录条目（仅名称+路由描述，不含 params_schema；降级路径也复用此投影）。"""
    return [
        {
            "id": spec.id,
            "name": spec.name,
            "description": spec.description,
            "enabled": spec.enabled,
            **({"mcp_source": spec.mcp_source} if include_mcp_source else {}),
        }
        for spec in catalog
    ]


def _search_catalog(catalog: list, q: str, include_mcp_source: bool = True) -> list[dict]:
    """匹配逻辑（独立函数：I4 降级只兜匹配失败，不兜目录获取）。"""
    q = q.lower()
    return [
        m for m in _catalog_projection(catalog, include_mcp_source)
        if q in m["name"].lower() or q in (m["description"] or "").lower()
    ]


def selected_names(result: dict[str, Any]) -> list[str]:
    """tool_search 结果 → 选中工具名（两段式注入的消费契约，tool_execute 唯一调用点）。

    matches 键存在即处理：空结果 → []（清空旧选中，防残留陈旧注入）。
    """
    matches = result.get("matches") or []
    return [m["name"] for m in matches if m.get("enabled")][:_SELECT_LIMIT]


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
        fallback = _catalog_projection(catalog, include_mcp_source=False)  # 不经过检索逻辑
        fallback.sort(key=lambda m: m["id"])
        return {"matches": fallback, "hint": None}
