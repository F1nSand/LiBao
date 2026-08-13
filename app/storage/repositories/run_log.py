"""运行日志数据访问（docs 04 §3.10）。append-only，trace_id 关联全链路；只增不改。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
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
