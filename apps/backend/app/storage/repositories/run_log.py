"""运行日志数据访问（《02》数据模型 §3.10）。append-only，trace_id 关联全链路；只增不改。

文件化：.agent/memory/default/trace/<session_id>.jsonl（任务流 → _tasks/<task_id>.jsonl）。
系统日志分页/聚合 = 扫描全部 trace 文件归并（个人量级文件数少，可接受）。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from app.storage.file.store import get_store
from app.storage.models.run_log import RunLog


class RunLogRepository:
    def __init__(self, session=None) -> None:
        self.session = session  # 兼容调用方传参（FileContext），文件化后不使用
        self.store = get_store()

    @staticmethod
    def _rel_path(session_id: uuid.UUID | None, task_id: uuid.UUID | None) -> str:
        if session_id is not None:
            return f"memory/default/trace/{session_id}.jsonl"
        return f"memory/default/trace/_tasks/{task_id}.jsonl"

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
        await self.store.jsonl_append(self._rel_path(session_id, task_id), log.to_dict())
        return log

    async def _scan_all(self) -> list[RunLog]:
        """扫描全部 trace 文件归并（按 created_at 升序）。"""
        traces = self.store.root / "memory" / "default" / "trace"
        if not traces.is_dir():
            return []
        rows: list[RunLog] = []
        for path in traces.rglob("*.jsonl"):
            records = await self.store.jsonl_list(str(path.relative_to(self.store.root)))
            rows.extend(RunLog.from_dict(r) for r in records)
        rows.sort(key=lambda r: r.created_at)
        return rows

    async def list_by_trace_id(self, trace_id: str) -> list[RunLog]:
        return [r for r in await self._scan_all() if r.trace_id == trace_id]

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
        rows = await self._scan_all()
        if trace_id:
            rows = [r for r in rows if r.trace_id == trace_id]
        if status:
            rows = [r for r in rows if r.status == status]
        if start is not None:
            rows = [r for r in rows if r.created_at >= start]
        if end is not None:
            rows = [r for r in rows if r.created_at <= end]
        rows.reverse()  # 新→旧
        return rows[offset : offset + limit], len(rows)

    async def aggregate_llm(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[tuple[Any, str, int, float]]:
        """按 (日, model) 内存聚合 LLM 调用（count + cost），替代 SQL GROUP BY。"""
        rows = await self._scan_all()
        agg: dict[tuple[date, str], list[int, float]] = {}
        for r in rows:
            if r.type != "llm":
                continue
            if start is not None and r.created_at < start:
                continue
            if end is not None and r.created_at > end:
                continue
            model = (r.input or {}).get("model") or ""
            key = (r.created_at.date(), model)
            usage = r.token_usage or {}
            cost = float(usage.get("cost") or 0.0)
            cur = agg.setdefault(key, [0, 0.0])
            cur[0] += 1
            cur[1] += cost
        return [
            (day, model, count, round(cost, 4))
            for (day, model), (count, cost) in sorted(agg.items())
        ]
