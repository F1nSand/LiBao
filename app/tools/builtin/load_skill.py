"""load_skill 内置 meta 工具（M7-A/M7-B）：按 name 取回 skill 正文（渐进式披露，docs 01 §4.2.1）。

优先查 org skills（DB，enabled）；未命中回退查工作区 skills（文件 `.agent/skills/<name>/SKILL.md`，
兼容旧 `skills/<name>/SKILL.md`）。org/工作区上下文缺失 → 降级错误结果（不抛）。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.core.errors import AppError
from app.services.skill import parse_skill_md
from app.storage.repositories.skill import SkillRepository
from app.tools.context import get_tool_org, get_tool_workspace_root


async def load_skill_handler(name: str) -> dict[str, Any]:
    # ① org skills（DB，enabled）
    org_id = get_tool_org()
    if org_id:
        try:
            skill = await SkillRepository().get_by_org_name(uuid.UUID(org_id), name)
            if skill is not None and skill.enabled:
                return {"name": skill.name, "description": skill.description, "body": skill.body}
        except Exception:  # noqa: BLE001  加载故障不击穿工具调用
            pass
    # ② 工作区 skills（文件，优先 .agent/skills/<name>/SKILL.md，兼容旧 skills/<name>/SKILL.md）
    root = get_tool_workspace_root()
    if root:
        for skills_dir in (Path(root) / ".agent" / "skills", Path(root) / "skills"):
            p = skills_dir / name / "SKILL.md"
            if not p.is_file():
                continue
            try:
                parsed = parse_skill_md(p.read_text(encoding="utf-8"))
            except AppError:
                continue
            if parsed["name"] == name:
                return {"name": name, "description": parsed["description"], "body": parsed["body"]}
    return {"error": f"skill {name} 不存在或未启用"}
