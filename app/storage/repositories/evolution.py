"""进化闭环·候选区数据访问（docs 03 §5.13 / docs 06 §5）。org 级隔离，跨 org 视为不存在。"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.storage.models.evolution import Candidate


class EvolutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_owned(self, org_id: uuid.UUID, candidate_id: uuid.UUID) -> Candidate | None:
        stmt = select(Candidate).where(
            Candidate.org_id == org_id, Candidate.id == candidate_id, Candidate.deleted_at.is_(None)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_candidates(
        self,
        org_id: uuid.UUID,
        *,
        status: str | None = None,
        search: str | None = None,
        limit: int,
        offset: int,
    ) -> tuple[list[Candidate], int]:
        base = select(Candidate).where(Candidate.org_id == org_id, Candidate.deleted_at.is_(None))
        if status is not None:
            base = base.where(Candidate.status == status)
        if search:
            base = base.where(Candidate.title.ilike(f"%{search}%"))
        total = int((await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
        stmt = base.order_by(Candidate.created_at.desc()).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars()), total

    async def create(
        self,
        *,
        org_id: uuid.UUID,
        title: str,
        change_type: str,
        source_type: str = "manual",
        status: str = "candidate",
        source_conversation_id: uuid.UUID | None = None,
        evidence: str | None = None,
        root_cause: str | None = None,
        proposed_change: str | None = None,
        expected_fix: str | None = None,
        affected_behaviors: list | None = None,
        validation_cases: list | None = None,
    ) -> Candidate:
        row = Candidate(
            org_id=org_id,
            title=title,
            source_type=source_type,
            change_type=change_type,
            status=status,
            source_conversation_id=source_conversation_id,
            evidence=evidence,
            root_cause=root_cause,
            proposed_change=proposed_change,
            expected_fix=expected_fix,
            affected_behaviors=affected_behaviors or [],
            validation_cases=validation_cases or [],
        )
        self.session.add(row)
        return row
