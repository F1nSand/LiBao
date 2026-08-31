"""系统观测领域服务（《02》接口契约 §5.8 / 《04》路线图 M5）。成本聚合逻辑收敛于此（M5 观测模块化）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.cost import provider_for
from app.storage.repositories.run_log import RunLogRepository


class SystemService:
    async def get_cost(
        self,
        db: Any,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        """成本/调用量统计：按 (日, model) SQL 聚合后 Python 归并 provider/series（《02》接口契约 §5.8 CostStat）。"""
        rows = await RunLogRepository(db).aggregate_llm(start=start, end=end)
        total_cost = 0.0
        calls = 0
        by_provider: dict[str, dict[str, Any]] = {}
        series: dict[str, dict[str, Any]] = {}
        for day, model, cnt, cost in rows:
            prov = provider_for(model or "")
            if provider and prov != provider:
                continue
            calls += int(cnt)
            total_cost += float(cost)
            p = by_provider.setdefault(prov, {"provider": prov, "cost": 0.0, "calls": 0})
            p["cost"] += float(cost)
            p["calls"] += int(cnt)
            day_str = day.isoformat() if day else ""
            s = series.setdefault(day_str, {"date": day_str, "cost": 0.0, "calls": 0})
            s["cost"] += float(cost)
            s["calls"] += int(cnt)
        return {
            "total_cost": round(total_cost, 6),
            "total_calls": calls,
            "by_provider": sorted(by_provider.values(), key=lambda x: -x["cost"]),
            "series": [series[k] for k in sorted(series)],
        }
