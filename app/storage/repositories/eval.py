"""评估数据访问（docs 04 §3.9）。集/用例/运行/结果；结果冗余 input/expected 快照。"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.eval import EvalCase, EvalResult, EvalRun, EvalSet


class EvalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- 集 ----

    async def create_set(self, org_id: uuid.UUID, name: str, description: str | None = None) -> EvalSet:
        row = EvalSet(org_id=org_id, name=name, description=description)
        self.session.add(row)
        return row

    async def list_sets(self, org_id: uuid.UUID) -> list[EvalSet]:
        stmt = select(EvalSet).where(EvalSet.org_id == org_id).order_by(EvalSet.created_at.desc())
        return list((await self.session.execute(stmt)).scalars())

    async def get_set(self, org_id: uuid.UUID, set_id: uuid.UUID) -> EvalSet | None:
        stmt = select(EvalSet).where(EvalSet.org_id == org_id, EvalSet.id == set_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def case_counts(self, set_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not set_ids:
            return {}
        stmt = (
            select(EvalCase.eval_set_id, func.count())
            .where(EvalCase.eval_set_id.in_(set_ids))
            .group_by(EvalCase.eval_set_id)
        )
        return {sid: int(n) for sid, n in (await self.session.execute(stmt)).all()}

    # ---- 用例 ----

    async def list_cases(self, set_id: uuid.UUID) -> list[EvalCase]:
        stmt = select(EvalCase).where(EvalCase.eval_set_id == set_id).order_by(EvalCase.created_at.asc())
        return list((await self.session.execute(stmt)).scalars())

    async def list_active_cases(self, set_id: uuid.UUID) -> list[EvalCase]:
        stmt = (
            select(EvalCase).where(EvalCase.eval_set_id == set_id, EvalCase.active.is_(True))
            .order_by(EvalCase.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars())

    async def create_case(self, set_id: uuid.UUID, input: str, expected: str, layer: str = "L3") -> EvalCase:
        row = EvalCase(eval_set_id=set_id, input=input, expected=expected, layer=layer, active=True)
        self.session.add(row)
        return row

    async def get_case(self, case_id: uuid.UUID) -> EvalCase | None:
        return await self.session.get(EvalCase, case_id)

    async def delete_case(self, case_id: uuid.UUID) -> None:
        row = await self.session.get(EvalCase, case_id)
        if row is not None:
            await self.session.delete(row)

    # ---- 集 ----

    async def count_runs(self, set_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(EvalRun).where(EvalRun.eval_set_id == set_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def delete_cases_for_set(self, set_id: uuid.UUID) -> None:
        from sqlalchemy import delete

        await self.session.execute(delete(EvalCase).where(EvalCase.eval_set_id == set_id))

    async def delete_set(self, set_id: uuid.UUID) -> None:
        row = await self.session.get(EvalSet, set_id)
        if row is not None:
            await self.session.delete(row)

    # ---- 运行 ----

    async def create_run(self, eval_set_id: uuid.UUID, baseline_run_id: uuid.UUID | None = None) -> EvalRun:
        row = EvalRun(eval_set_id=eval_set_id, baseline_run_id=baseline_run_id, status="pending", progress=0.0)
        self.session.add(row)
        return row

    async def get_run(self, run_id: uuid.UUID) -> EvalRun | None:
        return await self.session.get(EvalRun, run_id)

    async def list_runs(self) -> list[EvalRun]:
        stmt = select(EvalRun).order_by(EvalRun.created_at.desc())
        return list((await self.session.execute(stmt)).scalars())

    # ---- 结果 ----

    async def create_result(
        self,
        *,
        run_id: uuid.UUID,
        case_id: uuid.UUID,
        input: str,
        expected: str,
        actual: str | None,
        pass_: bool,
        score: float | None,
        latency_ms: int | None = None,
        cost: float | None = None,
    ) -> EvalResult:
        row = EvalResult(
            run_id=run_id, case_id=case_id, input=input, expected=expected, actual=actual,
            pass_=pass_, score=score, latency_ms=latency_ms, cost=cost,
        )
        self.session.add(row)
        return row

    async def list_results(self, run_id: uuid.UUID) -> list[EvalResult]:
        stmt = select(EvalResult).where(EvalResult.run_id == run_id).order_by(EvalResult.created_at.asc())
        return list((await self.session.execute(stmt)).scalars())
