"""工作区文件操作内置工具（M7-B，docs 01 §7.5 / §7.8）。

read_file/write_file/edit_file/glob/grep 走路径强限制（resolve_workspace_path）；
bash 走 LLM 语义审查（先审查再执行）。均读工作区根上下文（get_tool_workspace_root）；
无工作区上下文 → 降级错误结果（不抛，executor 正常打包）。
"""
from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.llm import LLMService
from app.tools.context import get_tool_workspace_root
from app.tools.filesystem import resolve_workspace_path

_MAX_READ = 20000
_MAX_WRITE = 100000
_MAX_BASH_OUT = 4000

# 工作区文件工具 id 集（build_initial_state 在工作区上下文时注入；默认 enabled=True，仅工作区可见）
FILE_TOOL_IDS = ("tl_read_file", "tl_write_file", "tl_edit_file", "tl_glob", "tl_grep", "tl_bash")


def _root() -> str | None:
    return get_tool_workspace_root()


async def read_file_handler(path: str) -> dict[str, Any]:
    root = _root()
    if not root:
        return {"error": "不在工作区上下文"}
    try:
        target = resolve_workspace_path(root, path)
    except AppError as exc:
        return {"error": exc.message}
    if not target.is_file():
        return {"error": f"文件不存在: {path}"}
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = target.read_bytes().decode("utf-8", errors="replace")
    return {"path": path, "content": content[:_MAX_READ]}


async def write_file_handler(path: str, content: str) -> dict[str, Any]:
    root = _root()
    if not root:
        return {"error": "不在工作区上下文"}
    try:
        target = resolve_workspace_path(root, path)
    except AppError as exc:
        return {"error": exc.message}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content[:_MAX_WRITE], encoding="utf-8")
    return {"path": path, "written": min(len(content), _MAX_WRITE)}


async def edit_file_handler(path: str, old_str: str, new_str: str) -> dict[str, Any]:
    root = _root()
    if not root:
        return {"error": "不在工作区上下文"}
    try:
        target = resolve_workspace_path(root, path)
    except AppError as exc:
        return {"error": exc.message}
    if not target.is_file():
        return {"error": f"文件不存在: {path}"}
    text = target.read_text(encoding="utf-8")
    if old_str not in text:
        return {"error": "old_str 未在文件中找到"}
    target.write_text(text.replace(old_str, new_str, 1), encoding="utf-8")
    return {"path": path, "edited": True}


async def glob_handler(pattern: str) -> dict[str, Any]:
    root = _root()
    if not root:
        return {"error": "不在工作区上下文"}
    root_p = Path(root)
    matches = [str(p.relative_to(root_p)) for p in root_p.rglob(pattern) if p.is_file()]
    return {"matches": sorted(matches)[:200]}


async def grep_handler(pattern: str, path: str | None = None) -> dict[str, Any]:
    root = _root()
    if not root:
        return {"error": "不在工作区上下文"}
    root_p = Path(root)
    base = root_p
    if path:
        try:
            base = resolve_workspace_path(root, path)
        except AppError as exc:
            return {"error": exc.message}
    try:
        rx = re.compile(pattern)
    except re.error:
        rx = re.compile(re.escape(pattern))
    files = [base] if base.is_file() else (list(base.rglob("*")) if base.is_dir() else [])
    hits: list[dict[str, Any]] = []
    for f in files[:500]:
        if not f.is_file():
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append({"file": str(f.relative_to(root_p)), "line": i, "text": line[:200]})
        except OSError:
            continue
        if len(hits) >= 200:
            break
    return {"matches": hits}


async def _review_command(command: str) -> dict[str, str]:
    """Bash 语义审查（LLM 分类，docs 01 §7.8 ②）：allow / block + 理由。审查失败保守 block。"""
    settings = get_settings()
    try:
        model = LLMService.build_model(settings.command_review_model or None)
        sys = (
            "你是 shell 命令安全审查器，判断命令在用户工作区（本地目录）内执行是否安全。\n"
            "只回复一行：ALLOW 或 BLOCK，可后跟一个空格 + 简短理由（≤40 字）。\n"
            "BLOCK 条件：rm -rf 等破坏性删除、访问工作区外路径(/etc /root /Windows C:\\ 等)、"
            "curl/wget 外传文件、读取凭证/密钥/环境变量、cron/启动项注入、fork 炸弹。其余 ALLOW。"
        )
        resp = await model.ainvoke([{"role": "system", "content": sys}, {"role": "user", "content": command}])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
    except Exception as exc:  # noqa: BLE001  审查失败保守 block
        return {"verdict": "block", "reason": f"审查失败: {str(exc)[:100]}"}
    first = text.strip().splitlines()[0].strip().upper() if text.strip() else ""
    if first.startswith("BLOCK"):
        return {"verdict": "block", "reason": text.strip()[:200]}
    return {"verdict": "allow", "reason": text.strip()[:200]}


async def bash_handler(command: str, cwd: str | None = None) -> dict[str, Any]:
    root = _root()
    if not root:
        return {"error": "不在工作区上下文"}
    workdir = Path(root)
    if cwd:
        try:
            workdir = resolve_workspace_path(root, cwd)
        except AppError as exc:
            return {"error": exc.message}
    # 语义审查：先审查再执行（审查是 bash 的唯一闸门，无容器沙箱）
    review = await _review_command(command)
    if review["verdict"] == "block":
        return {"error": f"命令被审查拦截: {review['reason']}", "verdict": "block", "reason": review["reason"]}
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            command,
            shell=True,
            cwd=str(workdir),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"error": "命令执行超时（120s）"}
    return {
        "stdout": result.stdout[-_MAX_BASH_OUT:],
        "stderr": result.stderr[-2000:],
        "returncode": result.returncode,
    }
