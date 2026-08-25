"""Skill 路由（M7-A 简化，docs 03 §5.14）。只读目录展示：全局 ~/.LiBao/skills + 工作区 .agent/skills。

2026-08-25：删 org CRUD 与 git 导入；skills 全部走文件系统，此处仅列目录供前端展示。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db, require_developer
from app.api.envelope import ok
from app.services.skill import discover_global_skills, discover_workspace_skills
from app.services.workspace import WorkspaceService
from app.storage.models.user import User

router = APIRouter()


@router.get("/skills")
async def list_skills(
    workspace_id: str | None = Query(None, description="指定则返回该工作区 skills；缺省返回全局 skills"),
    user: User = Depends(require_developer),
    db: Any = Depends(get_db),
):
    routes = (
        discover_workspace_skills((await WorkspaceService().get_in_org(db, user.org_id, workspace_id)).root_path)
        if workspace_id
        else discover_global_skills()
    )
    return ok([{"name": r["name"], "description": r["description"], "path": r["path"]} for r in routes])
