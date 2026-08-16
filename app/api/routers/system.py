"""系统路由（docs 03 §5.8）。health + 运行日志分页/单 trace 时间线（2f）。"""
from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.api.schemas.common import paged
from app.core.config import get_settings
from app.core.cost import provider_for
from app.services.serializers import serialize_run_log, serialize_trace_event
from app.storage.models.user import User
from app.storage.repositories.run_log import RunLogRepository

router = APIRouter()

# 前端 level → run_log.status 映射（run_log 无 level 列，用 status 承载成功/失败语义）
_LEVEL_TO_STATUS = {"INFO": "ok", "WARNING": "retried", "ERROR": "error"}


def _parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@router.get("/system/health")
async def health():
    settings = get_settings()
    return ok({"status": "ok", "service": "agent-backend", "env": settings.app_env, "time": int(time.time())})


@router.get("/system/logs")
async def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    trace_id: str | None = Query(None),
    level: str | None = Query(None, description="INFO/WARNING/ERROR → 映射 run_log.status"),
    start: str | None = Query(None, description="ISO 时间范围起点"),
    end: str | None = Query(None, description="ISO 时间范围终点"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    status = _LEVEL_TO_STATUS.get((level or "").upper())
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    repo = RunLogRepository(db)
    items, total = await repo.list_paged(
        limit=page_size, offset=(page - 1) * page_size, trace_id=trace_id, status=status, start=start_dt, end=end_dt
    )
    return ok(paged([serialize_run_log(lg) for lg in items], total, page, page_size))


@router.get("/system/evals")
async def evals_runs_alias(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """契约路径 GET /system/evals（docs 03 §5.8）：评估运行列表别名（同 /system/evals/runs）。"""
    from app.services.eval import EvalService

    return ok(await EvalService().list_runs(db))


@router.get("/system/cost")
async def get_cost(
    start: str | None = Query(None, description="ISO 时间范围起点"),
    end: str | None = Query(None, description="ISO 时间范围终点"),
    provider: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """成本/调用量统计（docs 03 §5.8 CostStat）：token_usage.cost 聚合（2h）。"""
    start_dt = _parse_iso(start)
    end_dt = _parse_iso(end)
    logs = await RunLogRepository(db).list_llm_in_range(start=start_dt, end=end_dt)
    total_cost = 0.0
    calls = 0
    by_provider: dict[str, dict] = {}
    series: dict[str, dict] = {}
    for log in logs:
        model = (log.input or {}).get("model", "")
        prov = provider_for(model)
        if provider and prov != provider:
            continue
        cost = float(((log.token_usage) or {}).get("cost", 0.0) or 0.0)
        calls += 1
        total_cost += cost
        p = by_provider.setdefault(prov, {"provider": prov, "cost": 0.0, "calls": 0})
        p["cost"] += cost
        p["calls"] += 1
        day = log.created_at.date().isoformat() if log.created_at else ""
        s = series.setdefault(day, {"date": day, "cost": 0.0, "calls": 0})
        s["cost"] += cost
        s["calls"] += 1
    return ok(
        {
            "total_cost": round(total_cost, 6),
            "total_calls": calls,
            "by_provider": sorted(by_provider.values(), key=lambda x: -x["cost"]),
            "series": [series[k] for k in sorted(series)],
        }
    )


@router.get("/system/logs/trace/{trace_id}")
async def get_trace(
    trace_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """单 trace 全链路时间线（TraceTimeline 消费）。"""
    logs = await RunLogRepository(db).list_by_trace_id(trace_id)
    return ok({"trace_id": trace_id, "events": [serialize_trace_event(lg) for lg in logs]})
