"""install_skill 内置工具（2026-08-25）：agent 上网找并下载 skill 到全局/工作区 skills 目录。

URL 可以是 git 仓库（clone --depth 1 扫描 SKILL.md）或裸 SKILL.md 文件（http 下载）。
校验 frontmatter（name/description）后落盘：默认全局 `~/.LiBao/skills/<name>/SKILL.md`，
target="workspace" 时落工作区 `.agent/skills/<name>/SKILL.md`。落盘后由 discover 自动识别
（渐进披露不破坏——路由进消息通道，正文 load_skill 取回）。
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.checkpoints.mutation import get_workspace_mutation_gateway
from app.core.config import get_settings
from app.core.errors import AppError
from app.services.skill import global_skills_dir, parse_skill_md, validate_skill_name, workspace_skills_dirs
from app.tools.builtin.fetch_url import _denied
from app.tools.context import get_tool_workspace_root

_GIT_URL_RE = re.compile(r"\.git(?:$|/)|^git@|^ssh://")
_MAX_DOWNLOAD_BYTES = 1_000_000  # SKILL.md 单文件大小上限（防超大下载/内存 DoS）


async def _download_text(url: str) -> str:
    """http 下载裸文本（SKILL.md），带大小上限。"""
    import httpx

    try:
        resp = await asyncio.to_thread(httpx.get, url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001  网络/HTTP 失败 → 可读错误
        raise RuntimeError(f"下载失败: {str(exc)[:120]}") from None
    if len(resp.content) > _MAX_DOWNLOAD_BYTES:
        raise RuntimeError(f"下载内容过大（>{_MAX_DOWNLOAD_BYTES // 1024}KB），拒绝")
    return resp.text


async def _clone_skill_md(url: str) -> str:
    """git clone --depth 1 → 返回第一个合法 SKILL.md 文本；失败抛 RuntimeError。"""
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
            raise RuntimeError("git clone 超时") from None
        if result.returncode != 0:
            raise RuntimeError(f"git clone 失败: {result.stderr[:200]}")
        for md in sorted(repo_dir.rglob("SKILL.md")):
            try:
                return md.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
    raise RuntimeError("仓库中未发现合法 SKILL.md")


async def install_skill_handler(url: str, target: str = "global") -> dict[str, Any]:
    """下载 skill 到全局（~/.LiBao/skills）或工作区（.agent/skills）。失败返回 error dict。"""
    if not url.strip():
        return {"error": "url 必填"}
    if target not in ("global", "workspace"):
        return {"error": "target 只能是 global 或 workspace"}
    # 安全：仅允许 http/https（防 git clone 本地路径/file:// 读任意仓库、.md 直达内网 SSRF）
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"error": "仅支持 http/https URL（防本地路径/file:///SSRF）"}
    from urllib.parse import urlparse

    if _denied(urlparse(url).hostname, get_settings().fetch_url_denylist):
        return {"error": "URL 命中出站黑名单"}
    # ① 下载 SKILL.md 文本（git 仓库 clone；裸 .md http 下载）
    try:
        if _GIT_URL_RE.search(url) or not url.lower().endswith(".md"):
            text = await _clone_skill_md(url)
        else:
            text = await _download_text(url)
    except RuntimeError as exc:
        return {"error": str(exc)}
    # ② 校验 frontmatter（name/description）
    try:
        parsed = parse_skill_md(text)
    except AppError as exc:
        return {"error": f"SKILL.md 非法: {exc.message}"}
    name = parsed["name"]
    if not validate_skill_name(name):
        return {"error": f"skill 名称非法: {name}（不能含 / \\ .. 或以 . 开头）"}
    # ③ 目标目录
    if target == "workspace":
        root = get_tool_workspace_root()
        if not root:
            return {"error": "target=workspace 需要工作区上下文"}
        dest_dir = workspace_skills_dirs(Path(root))[0][1] / name  # 优先 .agent/skills
    else:
        dest_dir = global_skills_dir() / name
    try:
        dest_file = dest_dir / "SKILL.md"
        gateway = get_workspace_mutation_gateway() if target == "workspace" else None
        if gateway is not None and gateway.enabled and root:
            relative = dest_file.relative_to(Path(root)).as_posix()
            await gateway.write_bytes(relative, text.encode("utf-8"))
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_file.write_text(text, encoding="utf-8")
    except OSError as exc:
        return {"error": f"写入失败: {exc}"}
    return {
        "skill": name,
        "description": parsed["description"],
        "path": str(dest_dir / "SKILL.md"),
        "target": target,
        "note": f"已安装到{'全局' if target == 'global' else '工作区'} skills 目录（下次对话自动识别）",
    }
