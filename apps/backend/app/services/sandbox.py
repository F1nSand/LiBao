"""命令执行后端偏好与可用性探测。"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import ERR_SANDBOX_UNAVAILABLE, AppError
from app.storage.models.sandbox_preference import SandboxPreference
from app.storage.models.user import User
from app.tools.shell_state import set_shell_mode

VALID_MODES = ("powershell", "git_bash", "docker")


def _probe_executable(command: str) -> tuple[bool, str]:
    path = shutil.which(command)
    return (True, path or command) if path else (False, f"未找到 {command}")


def _probe_docker() -> tuple[bool, str]:
    settings = get_settings()
    cli = str(settings.sandbox_docker_cli)
    if not Path(cli).exists() and shutil.which(cli) is None:
        return False, f"未找到 Docker CLI: {cli}"
    try:
        result = subprocess.run(
            [cli, "image", "inspect", str(settings.sandbox_docker_image)],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Docker daemon 不可用: {exc}"
    if result.returncode != 0:
        return False, "Docker 镜像不存在或 daemon 不可用"
    return True, "Docker daemon 与镜像可用"


def probe_backends() -> dict[str, dict[str, Any]]:
    powershell = _probe_executable("pwsh")
    from app.tools.sandbox import _workspace_shell_executable

    git_bash_path = _workspace_shell_executable("git_bash")
    git_bash = (True, git_bash_path) if git_bash_path else (False, "未找到 Git Bash")
    docker = _probe_docker()
    return {
        "powershell": {"available": powershell[0], "detail": powershell[1]},
        "git_bash": {"available": git_bash[0], "detail": git_bash[1]},
        "docker": {"available": docker[0], "detail": docker[1]},
    }


class SandboxService:
    async def _row(self, db: Any, org_id: uuid.UUID) -> SandboxPreference | None:
        rows = await db.store.table("sandbox_preferences").list(
            filter_fn=lambda row: row.org_id == org_id and row.deleted_at is None
        )
        return rows[0] if rows else None

    async def get(self, db: Any, user: User) -> dict[str, Any]:
        row = await self._row(db, user.org_id)
        mode = row.mode if row and row.mode in VALID_MODES else "powershell"
        settings = get_settings()
        return {
            "mode": mode,
            "review": {
                "enabled": bool(settings.bash_review_enabled),
                "configured": bool(settings.bash_review_endpoint and settings.bash_review_model),
            },
            "backends": await asyncio.to_thread(probe_backends),
        }

    async def set_mode(self, db: Any, user: User, mode: str) -> dict[str, Any]:
        if mode not in VALID_MODES:
            raise AppError(ERR_SANDBOX_UNAVAILABLE, f"未知沙箱模式: {mode}")
        backends = await asyncio.to_thread(probe_backends)
        if not backends[mode]["available"]:
            raise AppError(ERR_SANDBOX_UNAVAILABLE, f"沙箱后端不可用: {backends[mode]['detail']}")
        row = await self._row(db, user.org_id)
        if row is None:
            row = SandboxPreference(org_id=user.org_id, mode=mode)
            db.store.table("sandbox_preferences").register(row)
        else:
            row.mode = mode
        await db.commit()
        set_shell_mode(mode)  # 新请求默认值；已有图使用其 agent_config 快照。
        return await self.get(db, user)

    async def sync_runtime(self, db: Any | None = None, org_id: uuid.UUID | None = None) -> None:
        if db is None:
            return
        target = org_id or uuid.UUID(int=1)
        row = await self._row(db, target)
        set_shell_mode(row.mode if row and row.mode in VALID_MODES else "powershell")
