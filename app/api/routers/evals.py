"""评估路由（docs 03 §5.8，prefix /system/evals）。最小闭环：集/用例 CRUD + 运行 + 结果。"""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.api.envelope import ok
from app.services.eval import EvalService, run_eval
from app.services.serializers import serialize_eval_case, serialize_eval_run, serialize_eval_set
from app.storage.models.user import User

# 契约路径 /system/evals/*（docs 03 §5.8）：相对路径 + prefix，注册在 /api/v1 下即全路径
router = APIRouter(prefix="/system/evals")


class CreateEvalSetRequest(BaseModel):
    name: str
    description: str | None = None


class PatchEvalSetRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class AddEvalCaseRequest(BaseModel):
    input: str
    expected: str
    layer: str = "L3"  # L1-L5 分层（docs 06 §3.1）


class PatchEvalCaseRequest(BaseModel):
    active: bool


class RunEvalRequest(BaseModel):
    eval_set_id: uuid.UUID
    baseline_run_id: uuid.UUID | None = None  # 配对比较基线（docs 06 §2.4）


@router.get("/sets")
async def list_sets(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(await EvalService().list_sets(db, user))


@router.post("/sets")
async def create_set(
    req: CreateEvalSetRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(serialize_eval_set(await EvalService().create_set(db, user, req.name, req.description)))


@router.get("/sets/{eval_set_id}/cases")
async def list_cases(
    eval_set_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(await EvalService().list_cases(db, user, eval_set_id))


@router.put("/sets/{eval_set_id}")
async def patch_set(
    eval_set_id: uuid.UUID,
    req: PatchEvalSetRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(serialize_eval_set(await EvalService().patch_set(db, user, eval_set_id, req.name, req.description)))


@router.delete("/sets/{eval_set_id}")
async def delete_set(
    eval_set_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await EvalService().delete_set(db, user, eval_set_id)
    return ok()


@router.post("/sets/{eval_set_id}/cases")
async def add_case(
    eval_set_id: uuid.UUID,
    req: AddEvalCaseRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(
        serialize_eval_case(
            await EvalService().add_case(db, user, eval_set_id, req.input, req.expected, req.layer)
        )
    )


@router.patch("/sets/{eval_set_id}/cases/{case_id}")
async def patch_case(
    eval_set_id: uuid.UUID,
    case_id: uuid.UUID,
    req: PatchEvalCaseRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(serialize_eval_case(await EvalService().patch_case(db, user, eval_set_id, case_id, req.active)))


@router.delete("/sets/{eval_set_id}/cases/{case_id}")
async def delete_case(
    eval_set_id: uuid.UUID,
    case_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await EvalService().delete_case(db, user, eval_set_id, case_id)
    return ok()


@router.post("/run")
async def run_eval_endpoint(
    req: RunEvalRequest,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    run = await EvalService().create_run(db, user, req.eval_set_id, baseline_run_id=req.baseline_run_id)
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
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(await EvalService().list_runs(db, user))


@router.get("/runs/{run_id}")
async def get_run_detail(
    run_id: uuid.UUID,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(await EvalService().get_run_detail(db, user, run_id))


@router.get("/runs/{run_id}/pairwise")
async def get_pairwise(
    run_id: uuid.UUID,
    baseline_run_id: uuid.UUID = Query(...),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """配对比较（docs 06 §2.4）：候选 run vs 基线 run 逐题胜负矩阵 + 汇总。"""
    return ok(await EvalService().pairwise(db, user, run_id, baseline_run_id))
