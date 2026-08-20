"""Skill 领域服务（M7-A，docs 01 §4.2.1 / docs 03 §5.14）。

org 级 skill = SKILL.md（YAML frontmatter：name + description 路由描述 + body 正文）。
默认 enabled=false（约束优先）；支持 git 导入（clone → 扫描 SKILL.md → 单事务入库）。
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ERR_SKILL_IMPORT_FAILED,
    ERR_SKILL_INVALID,
    ERR_SKILL_NAME_CONFLICT,
    ERR_SKILL_NOT_FOUND,
    AppError,
)
from app.services.serializers import serialize_skill
from app.storage.models.skill import Skill
from app.storage.models.user import User
from app.storage.repositories.skill import SkillRepository

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def _parse_frontmatter(frontmatter: str) -> dict[str, str]:
    import yaml

    try:
        data = yaml.safe_load(frontmatter)
    except Exception:  # noqa: BLE001  非法 YAML → 空 dict → 上层校验报格式非法
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) if v is not None else "" for k, v in data.items()}


def parse_skill_md(text: str) -> dict[str, str]:
    """解析 SKILL.md：YAML frontmatter（name + description 必填，I7）+ 正文。"""
    m = _FRONTMATTER_RE.match(text)
    if m is None:
        raise AppError(ERR_SKILL_INVALID, "SKILL.md 缺少 frontmatter（--- name/description ---）")
    meta = _parse_frontmatter(m.group(1))
    name = (meta.get("name") or "").strip()
    description = (meta.get("description") or "").strip()
    if not name or not description:
        raise AppError(ERR_SKILL_INVALID, "SKILL.md frontmatter 必须含 name 与 description")
    return {"name": name, "description": description, "body": (m.group(2) or "").strip()}


def discover_workspace_skills(root_path: str | Path) -> list[dict[str, str]]:
    """扫描工作区 skills/*/SKILL.md → 路由描述（name + description）。非法 SKILL.md 跳过。"""
    skills_dir = Path(root_path) / "skills"
    out: list[dict[str, str]] = []
    if not skills_dir.is_dir():
        return out
    for md in sorted(skills_dir.glob("*/SKILL.md")):
        try:
            parsed = parse_skill_md(md.read_text(encoding="utf-8"))
        except AppError:
            continue
        out.append({"name": parsed["name"], "description": parsed["description"]})
    return out


class SkillService:
    async def list_for_org(
        self, db: AsyncSession, org_id: uuid.UUID, page: int, page_size: int, enabled: bool | None = None
    ) -> dict[str, Any]:
        repo = SkillRepository(db)
        items = await repo.list_for_org(org_id, enabled=enabled, limit=page_size, offset=(page - 1) * page_size)
        total = await repo.count_for_org(org_id, enabled=enabled)
        from app.api.schemas.common import paged

        return paged([serialize_skill(s) for s in items], total, page, page_size)

    async def enabled_skill_routes(self, db: AsyncSession, org_id: uuid.UUID) -> list[dict[str, str]]:
        """本组织已启用 skills 的路由描述（主 agent 注入静态前缀，镜像 tools enabled_tool_ids）。"""
        rows = await SkillRepository(db).list_enabled(org_id)
        return [{"name": s.name, "description": s.description} for s in rows]

    async def get_in_org(self, db: AsyncSession, org_id: uuid.UUID, skill_id: str) -> Skill:
        """按 id 或 name 解析（REST 用 id；tl_load_skill 用 name）。org 隔离。"""
        repo = SkillRepository(db)
        row: Skill | None = None
        try:
            row = await repo.get_by_id(uuid.UUID(skill_id))
        except ValueError:
            row = None
        if row is None or row.org_id != org_id or row.deleted_at is not None:
            row = await repo.get_by_org_name(org_id, skill_id)
        if row is None:
            raise AppError(ERR_SKILL_NOT_FOUND, "skill 不存在或无权访问")
        return row

    async def create(self, db: AsyncSession, user: User, req: Any) -> Skill:
        repo = SkillRepository(db)
        if await repo.name_exists(user.org_id, req.name):
            raise AppError(ERR_SKILL_NAME_CONFLICT, "同组织下已存在同名 skill")
        row = await repo.create(
            org_id=user.org_id,
            name=req.name,
            description=req.description or "",
            body=req.body or "",
            source="manual",
            enabled=False,  # 默认关闭原则
        )
        await db.commit()
        await db.refresh(row)
        return row

    async def set_enabled(self, db: AsyncSession, user: User, skill_id: str, enabled: bool) -> Skill:
        row = await self.get_in_org(db, user.org_id, skill_id)
        row.enabled = enabled
        await db.commit()
        await db.refresh(row)
        return row

    async def soft_delete(self, db: AsyncSession, user: User, skill_id: str) -> None:
        row = await self.get_in_org(db, user.org_id, skill_id)
        await SkillRepository(db).soft_delete(row)
        await db.commit()

    async def import_from_git(self, db: AsyncSession, user: User, url: str) -> dict[str, Any]:
        """git clone → 扫描 SKILL.md → 解析 → 单事务入库（重名跳过，失败整体回滚）。"""
        parsed: list[dict[str, str]] = []
        with tempfile.TemporaryDirectory() as tmp:
            repo_dir = Path(tmp) / "repo"
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["git", "clone", "--depth", "1", url, str(repo_dir)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except subprocess.TimeoutExpired:
                raise AppError(ERR_SKILL_IMPORT_FAILED, "git clone 超时") from None
            if result.returncode != 0:
                raise AppError(ERR_SKILL_IMPORT_FAILED, f"git clone 失败: {result.stderr[:200]}")
            for md in repo_dir.rglob("SKILL.md"):
                try:
                    parsed.append(parse_skill_md(md.read_text(encoding="utf-8")))
                except AppError:
                    continue  # 单个非法 skill 跳过，不击穿整体导入
        if not parsed:
            raise AppError(ERR_SKILL_IMPORT_FAILED, "仓库中未发现合法 SKILL.md")

        repo = SkillRepository(db)
        created = 0
        for p in parsed:
            if await repo.name_exists(user.org_id, p["name"]):
                continue  # 重名跳过（幂等重导入）
            await repo.create(
                org_id=user.org_id,
                name=p["name"],
                description=p["description"],
                body=p["body"],
                source="git",
                enabled=False,
            )
            created += 1
        await db.commit()
        return {"imported": created, "skipped": len(parsed) - created}
