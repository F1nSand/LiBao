"""运行日志数据访问（docs 04 §3.10）。append-only，trace_id 关联全链路；只增不改。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
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

    async def list_llm_in_range(self, *, start: datetime | None = None, end: datetime | None = None) -> list[RunLog]:
        """LLM 调用（type=llm）成本聚合原料（2h /system/cost）。"""
        stmt = select(RunLog).where(RunLog.type == "llm")
        if start is not None:
            stmt = stmt.where(RunLog.created_at >= start)
        if end is not None:
            stmt = stmt.where(RunLog.created_at <= end)
        return list((await self.session.execute(stmt)).scalars())
