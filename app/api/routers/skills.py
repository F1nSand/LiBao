"""Skill 路由（M7-A，docs 03 §5.14）。CRUD + git 导入（developer+）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_developer
from app.api.envelope import ok
from app.api.schemas.skill import CreateSkillRequest, SkillImportRequest, SkillToggleRequest
from app.services.serializers import serialize_skill
from app.services.skill import SkillService
from app.storage.models.user import User

router = APIRouter()


@router.post("/skills/import")  # 必须在 /skills/{skill_id} 之前，避免被 path 参数吞掉
async def import_skills(
    req: SkillImportRequest,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    return ok(await SkillService().import_from_git(db, user, req.url))


@router.get("/skills")
async def list_skills(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    enabled: bool | None = Query(None),
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    data = await SkillService().list_for_org(db, user.org_id, page, page_size, enabled=enabled)
    return ok(data)


@router.post("/skills")
async def create_skill(
    req: CreateSkillRequest,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    row = await SkillService().create(db, user, req)
    return ok(serialize_skill(row))


@router.get("/skills/{skill_id}")
async def get_skill(
    skill_id: str,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    row = await SkillService().get_in_org(db, user.org_id, skill_id)
    return ok(serialize_skill(row))


@router.patch("/skills/{skill_id}")
async def toggle_skill(
    skill_id: str,
    req: SkillToggleRequest,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    row = await SkillService().set_enabled(db, user, skill_id, req.enabled)
    return ok(serialize_skill(row))


@router.delete("/skills/{skill_id}")
async def delete_skill(
    skill_id: str,
    user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    await SkillService().soft_delete(db, user, skill_id)
    return ok()
