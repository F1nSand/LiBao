"""评估路由（docs 03 §5.8，prefix /system/evals）。最小闭环：集/用例 CRUD + 运行 + 结果。"""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.api.envelope import ok
from app.services.eval import EvalService, run_eval
from app.services.serializers import serialize_eval_case, serialize_eval_run, serialize_eval_set
from app.storage.models.user import User

router = APIRouter()


class CreateEvalSetRequest(BaseModel):
    name: str
    description: str | None = None


class AddEvalCaseRequest(BaseModel):
    input: str
    expected: str


class PatchEvalCaseRequest(BaseModel):
    active: bool


class RunEvalRequest(BaseModel):
    eval_set_id: uuid.UUID


@router.get("/sets")
async def list_sets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await EvalService().list_sets(db, user))


@router.post("/sets")
async def create_set(
    req: CreateEvalSetRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(serialize_eval_set(await EvalService().create_set(db, user, req.name, req.description)))


@router.post("/sets/{eval_set_id}/cases")
async def add_case(
    eval_set_id: uuid.UUID,
    req: AddEvalCaseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(serialize_eval_case(await EvalService().add_case(db, user, eval_set_id, req.input, req.expected)))


@router.patch("/sets/{eval_set_id}/cases/{case_id}")
async def patch_case(
    eval_set_id: uuid.UUID,
    case_id: uuid.UUID,
    req: PatchEvalCaseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(serialize_eval_case(await EvalService().patch_case(db, user, eval_set_id, case_id, req.active)))


@router.post("/run")
async def run_eval_endpoint(
    req: RunEvalRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await EvalService().create_run(db, user, req.eval_set_id)
    # 后台链（镜像 kb_pipeline；M4 队列接缝）
    asyncio.create_task(
        run_eval(
            graph=request.app.state.graph,
            sessionmaker=request.app.state.sessionmaker,
            eval_run_id=run.id,
        )
    )
    return ok(serialize_eval_run(run))


@router.get("/runs")
async def list_runs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await EvalService().list_runs(db))


@router.get("/runs/{run_id}")
async def get_run_detail(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return ok(await EvalService().get_run_detail(db, run_id))
