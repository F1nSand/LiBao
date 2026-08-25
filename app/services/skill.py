"""Skill 领域服务（M7-A，docs 01 §4.2.1 / docs 03 §5.14）。

2026-08-25 简化：删除 org skills 层与 git 导入，skills 全部走文件系统——
全局 `~/.LiBao/skills` + 工作区 `.agent/skills`（两级）。SKILL.md = YAML frontmatter
（name + description 路由描述）+ 正文；渐进披露——只列路由，正文 tl_load_skill 按需取回。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import ERR_SKILL_INVALID, AppError

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def global_skills_dir() -> Path:
    """全局 skills 根目录 `~/.LiBao/skills`（expanduser 解析；打包后安装根 .LiBao/skills，类似 ~/.claude）。"""
    return Path(get_settings().skills_root).expanduser()


def validate_skill_name(name: str) -> bool:
    """skill 名安全校验（防路径穿越，允许 Unicode 字母/数字/下划线/连字符）：不空、≤64、不以 . 开头、不含 / \\ ..。"""
    if not name or len(name) > 64:
        return False
    if name.startswith(".") or "/" in name or "\\" in name or ".." in name:
        return False
    return True


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


def read_skill_file(p: Path) -> dict[str, str] | None:
    """读单个 SKILL.md（frontmatter name 须与目录名一致）→ {name, description, body}；非法/缺失 → None。

    统一的「读取 + 异常抑制 + name==目录名校验」入口（发现与取回共用，保证「能列出的必能取回」）。
    """
    if not p.is_file():
        return None
    try:
        parsed = parse_skill_md(p.read_text(encoding="utf-8-sig"))  # utf-8-sig 兼容 Windows BOM
    except (AppError, OSError, UnicodeDecodeError):
        return None
    if parsed["name"] != p.parent.name:
        return None
    return parsed


def discover_skills_dir(skills_dir: Path, seen: set[str] | None = None) -> list[dict[str, str]]:
    """扫描单个 skills 目录 `*/SKILL.md` → 路由描述（name + description + path）。

    非法 / 非 UTF-8 / 不可读 SKILL.md 跳过（不击穿扫描）；frontmatter name 须与目录名一致
    （否则路由悬空——能列取不回，2026-08-25 review 修复）。utf-8-sig 兼容 Windows 常见 BOM。
    """
    out: list[dict[str, str]] = []
    if not skills_dir.is_dir():
        return out
    for md in sorted(skills_dir.glob("*/SKILL.md")):
        parsed = read_skill_file(md)
        if parsed is None:
            continue
        if seen is not None:
            if parsed["name"] in seen:
                continue
            seen.add(parsed["name"])
        out.append({"name": parsed["name"], "description": parsed["description"], "path": f"{parsed['name']}/SKILL.md"})
    return out


def workspace_skills_dirs(root: Path) -> tuple[tuple[str, Path], ...]:
    """工作区 skills 目录（有序，优先级在前）：`.agent/skills` 优先，兼容旧 `skills/`。"""
    return ((".agent/skills", root / ".agent" / "skills"), ("skills", root / "skills"))


def discover_workspace_skills(root_path: str | Path) -> list[dict[str, str]]:
    """扫描工作区 skills → 路由描述（name + description）+ 实际位置 path。非法 SKILL.md 跳过。

    M7-B T7a 重定位：优先 `.agent/skills/*/SKILL.md`，兼容旧 `skills/*/SKILL.md`；
    同名以 `.agent/` 为准（项目级覆盖旧路径）。
    """
    root = Path(root_path)
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for prefix, skills_dir in workspace_skills_dirs(root):
        for r in discover_skills_dir(skills_dir, seen):
            out.append({**r, "path": f"{prefix}/{r['name']}/SKILL.md"})
    return out


def merge_skill_routes(
    workspace_routes: list[dict[str, str]], global_routes: list[dict[str, str]]
) -> list[dict[str, str]]:
    """两级优先级合并：同名工作区覆盖全局（注入与取回一致的规则显式化）。"""
    by_name: dict[str, dict[str, str]] = {s["name"]: s for s in global_routes}
    for s in workspace_routes:
        by_name[s["name"]] = s
    return list(by_name.values())


def discover_global_skills(root_path: str | Path | None = None) -> list[dict[str, str]]:
    """扫描全局 skills 根目录 `<root>/*/SKILL.md` → 路由描述（2026-08-25 简化）。

    像 Claude Code 的 `~/.claude/skills/`：放 SKILL.md 即自动识别；渐进披露——只列路由，
    正文经 tl_load_skill 按需取回。两级优先级：工作区 .agent/skills > 全局。
    """
    routes = discover_skills_dir(Path(root_path) if root_path else global_skills_dir())
    return [{**r, "path": f"skills/{r['name']}/SKILL.md"} for r in routes]


def _md_index(text: str, stem: str) -> tuple[str, str]:
    """md 文本 → (title, summary)：frontmatter title 优先（否则文件名）；summary = 正文首行 ≤120 字。"""
    m = _FRONTMATTER_RE.match(text)
    title = ""
    body = text
    if m is not None:
        meta = _parse_frontmatter(m.group(1))
        title = (meta.get("title") or "").strip()
        body = (m.group(2) or "").strip()
    if not title:
        title = stem
    first_line = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    return title, first_line[:120]


def _read_md_dir(directory: Path) -> list[dict[str, str]]:
    """读目录下 *.md → 索引 [{name, title, summary}]（P3 起只读索引，正文不落内存。

    项目记忆/知识铁律：正文不注入 system prompt；agent 需细节时用 read_file 按需取回。
    """
    if not directory.is_dir():
        return []
    out: list[dict[str, str]] = []
    for md in sorted(directory.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8-sig").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if not text:
            continue
        title, summary = _md_index(text, md.stem)
        out.append({"name": md.stem, "title": title, "summary": summary})
    return out


def discover_workspace_agent(root_path: str | Path) -> dict[str, Any]:
    """扫描工作区 `.agent/` → 项目级能力叠加（skills 路由 + agent.md + memory/knowledge 索引）。

    M7-B T7a/T8 重定位：agent 运行时 = 全局基座（全局 skills + 长期记忆 + 知识库 + 工具）
    + 项目级 `.agent/`（skills/memory/knowledge/agent.md）。此处只发现，注入在 build_initial_state。
    P3：memory/knowledge 只返回索引（name/title/summary），正文由 read_file 按需读取。
    """
    root = Path(root_path)
    agent_dir = root / ".agent"
    out: dict[str, Any] = {
        "skills": discover_workspace_skills(root_path),
        "agent_md": "",
        "memory": _read_md_dir(agent_dir / "memory"),
        "knowledge": _read_md_dir(agent_dir / "knowledge"),
    }
    agent_md = agent_dir / "agent.md"
    if agent_md.is_file():
        try:
            out["agent_md"] = agent_md.read_text(encoding="utf-8-sig").strip()
        except (OSError, UnicodeDecodeError):
            pass
    return out
