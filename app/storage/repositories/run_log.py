"""运行日志数据访问（docs 04 §3.10）。append-only，trace_id 关联全链路；只增不改。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.run_log import RunLog


class RunLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        trace_id: str,
        session_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        node: str = "",
        type: str = "node",
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        token_usage: dict[str, Any] | None = None,
        duration_ms: int = 0,
        status: str = "ok",
    ) -> RunLog:
        log = RunLog(
            trace_id=trace_id,
            session_id=session_id,
            task_id=task_id,
            node=node,
            type=type,
            input=input or {},
            output=output or {},
            token_usage=token_usage,
            duration_ms=duration_ms,
            status=status,
        )
        self.session.add(log)
        return log

    async def list_by_trace_id(self, trace_id: str) -> list[RunLog]:
        stmt = select(RunLog).where(RunLog.trace_id == trace_id).order_by(RunLog.created_at.asc())
        return list((await self.session.execute(stmt)).scalars())

    async def list_paged(
        self,
        *,
        limit: int,
        offset: int,
        trace_id: str | None = None,
        status: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[list[RunLog], int]:
        """系统日志分页（2f）：trace_id/status/时间范围过滤，新→旧。"""
        stmt = select(RunLog)
        if trace_id:
            stmt = stmt.where(RunLog.trace_id == trace_id)
        if status:
            stmt = stmt.where(RunLog.status == status)
        if start is not None:
            stmt = stmt.where(RunLog.created_at >= start)
        if end is not None:
            stmt = stmt.where(RunLog.created_at <= end)
        total = int(
            (await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        )
        items_stmt = stmt.order_by(RunLog.created_at.desc()).limit(limit).offset(offset)
        return list((await self.session.execute(items_stmt)).scalars()), total

    async def aggregate_llm(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[tuple[Any, str, int, float]]:
        """按 (日, model) SQL GROUP BY 聚合 LLM 调用（count + cost），替代 Python 全量循环（M5 观测）。"""
        stmt = (
            select(
                func.date(RunLog.created_at).label("day"),
                RunLog.input["model"].as_string().label("model"),
                func.count().label("calls"),
                # token_usage.cost 必须进聚合，否则违反 GROUP BY（实测 /system/cost 50001）
                func.sum(func.coalesce(func.cast(RunLog.token_usage["cost"].astext, Float), 0.0)).label("cost"),
            )
            .where(RunLog.type == "llm")
            .group_by("day", "model")
            .order_by("day")
        )
        if start is not None:
            stmt = stmt.where(RunLog.created_at >= start)
        if end is not None:
            stmt = stmt.where(RunLog.created_at <= end)
        return list((await self.session.execute(stmt)).all())
