"""工作区文件操作内置工具（M7-B，docs 01 §7.5 / §7.8）。

read_file/write_file/edit_file/glob/grep 走路径强限制（resolve_workspace_path）；
bash 走 LLM 语义审查（先审查再执行）。均读工作区根上下文（get_tool_workspace_root）；
无工作区上下文 → 降级错误结果（不抛，executor 正常打包）。
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.llm import LLMService
from app.core.messages import message_text
from app.tools.context import get_tool_workspace_root
from app.tools.filesystem import resolve_workspace_path

_MAX_READ = 20000
_MAX_WRITE = 100000
_MAX_BASH_OUT = 4000

# 工作区文件工具 id 集（build_initial_state 在工作区上下文时注入；默认 enabled=True，仅工作区可见）
FILE_TOOL_IDS = ("tl_read_file", "tl_write_file", "tl_edit_file", "tl_glob", "tl_grep", "tl_bash", "tl_undo_file")

# 回滚备份（2026-08-24）：write/edit 写前备份到 .agent/.undo/，tl_undo_file 恢复最近一份
_UNDO_DIR = ".agent/.undo"
_UNDO_KEEP_MAX = 20


def _backup_file(root: str, target: Path) -> str | None:
    """写前备份（仅已存在文件；超限清最旧）。返回备份文件名（未备份返回 None）。"""
    if not target.is_file():
        return None
    rel = str(target.relative_to(Path(root))).replace("\\", "_").replace("/", "_")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"{stamp}_{rel}_{target.stat().st_size}.bak"
    d = Path(root) / _UNDO_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, d / name)
    except OSError:
        return None  # 备份失败不阻断写（best-effort）
    backups = sorted(d.glob("*.bak"))
    for old in backups[:-_UNDO_KEEP_MAX]:
        try:
            old.unlink()
        except OSError:
            pass
    return name


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
    backup = _backup_file(root, target)  # 覆盖已存在文件前备份（回滚用）
    target.write_text(content[:_MAX_WRITE], encoding="utf-8")
    result: dict[str, Any] = {"path": path, "written": min(len(content), _MAX_WRITE)}
    if backup:
        result["note"] = f"已备份旧版（{backup}），如需撤销用 undo_file('{path}')"
    return result


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
    backup = _backup_file(root, target)  # 写前备份（回滚用）
    target.write_text(text.replace(old_str, new_str, 1), encoding="utf-8")
    result: dict[str, Any] = {"path": path, "edited": True}
    if backup:
        result["note"] = f"已备份旧版（{backup}），如需撤销用 undo_file('{path}')"
    return result


async def undo_file_handler(path: str) -> dict[str, Any]:
    """从 .agent/.undo/ 自动备份恢复最近一份（恢复前也备份当前内容，undo 可逆）。"""
    root = _root()
    if not root:
        return {"error": "不在工作区上下文"}
    try:
        target = resolve_workspace_path(root, path)
    except AppError as exc:
        return {"error": exc.message}
    rel_key = str(target.relative_to(Path(root))).replace("\\", "_").replace("/", "_")
    d = Path(root) / _UNDO_DIR
    if not d.is_dir():
        return {"error": f"没有可恢复的备份: {path}", "path": path}
    backups = sorted(d.glob(f"*_{rel_key}_*.bak"))
    if not backups:
        return {"error": f"没有可恢复的备份: {path}", "path": path}
    latest = backups[-1]
    try:
        content = latest.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": f"备份读取失败: {exc}"}
    _backup_file(root, target)  # 恢复前备份当前内容（undo 可逆）
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": path, "restored": True, "from": latest.name, "note": f"已从备份恢复（{latest.name}）"}


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
    """Bash 语义审查（LLM 分类，docs 01 §7.8 ②）：allow / block + 理由。审查失败走快速通道降级。"""
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
        # DeepSeek v4-flash 的 content 是 blocks 列表——必须用 message_text 提取（str() 会取到 Python repr）
        text = resp.content if isinstance(resp.content, str) else message_text(resp.content)
    except Exception as exc:  # noqa: BLE001  审查模型失败降级快速通道（勿无脑 block 把 bash 全禁）
        fast = _fast_review(command)
        if fast == "block":
            return {"verdict": "block", "reason": "命中危险命令模式"}
        if fast == "allow":
            return {"verdict": "allow", "reason": "只读快速通道"}
        return {
            "verdict": "allow",
            "reason": f"审查模型暂不可用（{str(exc)[:80]}），已放行——白名单外复杂命令请人工复核",
        }
    first = text.strip().splitlines()[0].strip().upper() if text.strip() else ""
    if first.startswith("BLOCK"):
        return {"verdict": "block", "reason": text.strip()[:200]}
    return {"verdict": "allow", "reason": text.strip()[:200]}


# Windows 下 Git Bash 可执行文件常见安装路径（优先于 shutil.which——which 可能命中 System32 的 WSL 中继）
_BASH_CANDIDATES = (
    "C:/Program Files/Git/usr/bin/bash.exe",
    "C:/Program Files/Git/bin/bash.exe",
    "C:/Program Files (x86)/Git/bin/bash.exe",
)


@lru_cache(maxsize=1)
def _bash_executable() -> str | None:
    """Windows 上探测 Git Bash（POSIX shell）。命中返回绝对路径，否则 None（降级 cmd）。

    2026-08-24 实证：shutil.which("bash") 在 cmd/PowerShell PATH 下会命中
    C:\\Windows\\System32\\bash.exe（WSL 中继）→ 每次执行 execvpe(/bin/bash) failed，
    工作区 bash 工具全挂。修复：显式 Git Bash 路径优先 + 排除 System32。
    """
    for p in _BASH_CANDIDATES:
        if Path(p).exists():
            return p
    found = shutil.which("bash")
    if found:
        resolved = Path(found).resolve()
        system32 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
        if resolved != system32 and not resolved.is_relative_to(system32):
            return str(resolved)
    return None


# ---- bash 语义审查快速通道（A4）：只读简单命令跳过 LLM 审查；危险模式硬拦 ----
_SHELL_META = (";", "&&", "||", "|", ">", "<", "$(", "`", "&")
_READONLY_TOKENS = {
    "ls", "pwd", "echo", "cat", "head", "tail", "wc", "date", "which", "find", "grep",
    "tree", "file", "dir", "du", "df", "stat", "realpath", "uname",
}
_GIT_READONLY_SUBCOMMANDS = {"status", "log", "diff", "branch", "remote", "show", "rev-parse", "--version"}
_BLOCK_MARKERS = (
    "rm -rf", "rm -fr", "mkfs", "dd if=", "chmod 777", "chown", "cron", "printenv",
    "env ", "cat /etc/", "~/.ssh", ".git/config", "git push", "git reset --hard", "git clean",
)


def _fast_review(command: str) -> str | None:
    """快速通道：黑名单命中 → 'block'；只读简单命令 → 'allow'；其余 → None（走 LLM 审查）。"""
    stripped = command.strip()
    low = stripped.lower()
    for marker in _BLOCK_MARKERS:
        if marker in low:
            return "block"
    has_meta = any(m in stripped for m in _SHELL_META)
    first = stripped.split()[0].lower() if stripped.split() else ""
    if first == "git":
        parts = stripped.split()
        if not has_meta and len(parts) >= 2 and parts[1] in _GIT_READONLY_SUBCOMMANDS:
            return "allow"
        return None  # git 写操作走 LLM 审查
    if not has_meta and first in _READONLY_TOKENS:
        return "allow"
    return None


async def _run_shell(command: str, workdir: str) -> subprocess.CompletedProcess:
    """执行 shell 命令（bash 工具底层）。

    Windows 优先走 Git Bash（POSIX 语义：多行 -c / 引号 / 管道 / && 正确解析，
    修复 shell=True 走 cmd 时「多行脚本被拆散 → returncode 0 但未执行」）；
    非 Windows 或探测不到 bash 时降级 shell=True（cmd，维持旧行为）。
    """
    bash = _bash_executable() if sys.platform == "win32" else None
    if bash:
        return await asyncio.to_thread(
            subprocess.run,
            [bash, "-c", command],
            cwd=workdir,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    return await asyncio.to_thread(
        subprocess.run,
        command,
        shell=True,
        cwd=workdir,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


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
    # 语义审查：快速通道（只读白名单 / 危险黑名单）→ LLM 审查（bash 的唯一闸门，无容器沙箱）
    fast = _fast_review(command)
    if fast == "block":
        return {"error": "命令被审查拦截（安全黑名单）", "verdict": "block", "reason": "命中危险命令模式"}
    if fast is None:
        review = await _review_command(command)
        if review["verdict"] == "block":
            return {"error": f"命令被审查拦截: {review['reason']}", "verdict": "block", "reason": review["reason"]}
    try:
        result = await _run_shell(command, str(workdir))
    except subprocess.TimeoutExpired:
        return {"error": "命令执行超时（120s）"}
    stdout = result.stdout[-_MAX_BASH_OUT:]
    stderr = result.stderr[-2000:]
    payload: dict[str, Any] = {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": result.returncode,
    }
    # 失败可读化：给 LLM 恢复路径（环境/语法/路径），杜绝「环境坏了」误判 + 盲目重试
    if result.returncode != 0:
        if "WSL" in stderr or "execvpe" in stderr:
            payload["hint"] = (
                "检测到 WSL bash 调用失败——本机 Git Bash 应可用；命令未真正执行，"
                "重试前检查命令语法，或改用 read_file/glob 完成只读操作。"
            )
        else:
            payload["hint"] = (
                f"命令执行失败（exit {result.returncode}）——先读 stderr 判断原因（语法/路径/权限/环境），"
                "修正后重试；不要盲目重复同一命令，写操作可用 read_file 验证副作用。"
            )
    # C：退出码 0 但无输出 → 提示可能未真正执行，引导 LLM 验证副作用（而非盲目重试）
    elif not stdout.strip() and not stderr.strip():
        payload["note"] = (
            "命令退出码 0 但无 stdout/stderr——若预期有输出，可能未真正执行；"
            "用 read_file 或 `ls` 验证副作用。"
        )
    return payload
