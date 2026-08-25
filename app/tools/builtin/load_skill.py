"""load_skill 内置 meta 工具（M7-A/M7-B）：按 name 取回 skill 正文（渐进式披露，docs 01 §4.2.1）。

两级查找（2026-08-25 简化，删 org）：① 工作区 `.agent/skills/<name>/SKILL.md`（兼容旧 `skills/`）；
② 全局 `~/.LiBao/skills/<name>/SKILL.md`。上下文缺失 → 降级错误结果（不抛）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.skill import global_skills_dir, read_skill_file, validate_skill_name, workspace_skills_dirs
from app.tools.context import get_tool_workspace_root


async def load_skill_handler(name: str) -> dict[str, Any]:
    # 安全：skill 名校验防路径穿越（meta 工具始终可用，必须拦截 ../ 类参数）
    if not validate_skill_name(name):
        return {"error": f"skill 名称非法: {name}"}
    # ① 工作区 skills（文件，优先 .agent/skills/<name>/SKILL.md，兼容旧 skills/<name>/SKILL.md）
    root = get_tool_workspace_root()
    if root:
        for _, skills_dir in workspace_skills_dirs(Path(root)):
            hit = read_skill_file(skills_dir / name / "SKILL.md")
            if hit:
                return hit
    # ② 主 agent 全局 skills（~/.LiBao/skills/<name>/SKILL.md）
    hit = read_skill_file(global_skills_dir() / name / "SKILL.md")
    if hit:
        return hit
    return {"error": f"skill {name} 不存在或未启用"}
