"""进化闭环·候选区路由（docs 03 §5.13）。admin-only（M6-1 require_admin）。

契约：候选不存在 40401、状态不允许 40020（HTTP 200 + 信封 code，裸 404 会触发前端 FEATURE.evolution 降级）。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.api.envelope import ok
from app.api.schemas.evolution import CreateCandidateRequest
from app.services.evolution import EvolutionService, serialize_candidate
from app.storage.models.user import User

router = APIRouter(prefix="/evolution")


@router.get("/candidates")
async def list_candidates(
    status: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        await EvolutionService().list_candidates(
            db, user, status=status, search=search, page=page, page_size=page_size
        )
    )


@router.get("/candidates/{candidate_id}")
async def get_candidate(
    candidate_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    c = await EvolutionService().get_candidate_owned(db, user, candidate_id)
    return ok(serialize_candidate(c))


@router.post("/candidates")
async def create_candidate(
    req: CreateCandidateRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """手动创建候选（source_type=manual）。不在前端契约内，供测试/演示。"""
    c = await EvolutionService().create_candidate(
        db,
        user,
        title=req.title,
        change_type=req.change_type,
        evidence=req.evidence,
        root_cause=req.root_cause,
        proposed_change=req.proposed_change,
        expected_fix=req.expected_fix,
        affected_behaviors=req.affected_behaviors,
        validation_cases=req.validation_cases,
    )
    return ok(serialize_candidate(c))


@router.post("/candidates/{candidate_id}/validate")
async def validate_candidate(
    candidate_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    c = await EvolutionService().validate_candidate(db, user, candidate_id, request.app.state.graph)
    return ok(serialize_candidate(c))


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    c = await EvolutionService().reject_candidate(db, user, candidate_id)
    return ok(serialize_candidate(c))


@router.post("/candidates/{candidate_id}/publish")
async def publish_candidate(
    candidate_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    c = await EvolutionService().publish_candidate(db, user, candidate_id)
    return ok(serialize_candidate(c))


@router.post("/candidates/{candidate_id}/rollback")
async def rollback_candidate(
    candidate_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    c = await EvolutionService().rollback_candidate(db, user, candidate_id)
    return ok(serialize_candidate(c))
