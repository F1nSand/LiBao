"""沙箱运行契约（docs 01 §7.3 D1）。

命令只携带容器内部路径；实际 Docker 进程边界由后续 runner 负责。NONE 保持宿主执行，
DOCKER/MICROVM 的级别可被配置和持久化，其中 MICROVM 暂不提供执行实现。
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

logger = logging.getLogger(__name__)


class SandboxLevel(enum.StrEnum):
    NONE = "none"
    DOCKER = "docker"
    MICROVM = "microvm"


class SandboxErrorCode(enum.StrEnum):
    UNAVAILABLE = "sandbox_unavailable"
    IMAGE_MISSING = "sandbox_image_missing"
    INVALID_WORKDIR = "sandbox_invalid_workdir"
    UNSUPPORTED_TOOL = "sandbox_unsupported_tool"
    START_FAILED = "sandbox_start_failed"
    TIMEOUT = "sandbox_timeout"
    EXIT_NONZERO = "sandbox_exit_nonzero"


class SandboxFailure(RuntimeError):
    """沙箱边界的结构化失败；只应由执行器转换为 ToolResult。"""

    def __init__(
        self,
        code: SandboxErrorCode,
        message: str,
        retryable: bool = False,
        output: dict[str, Any] | None = None,
    ) -> None:
        self.code = SandboxErrorCode(code)
        self.message = message
        self.retryable = retryable
        self.output = output
        super().__init__(f"{self.code.value}: {message}")


def _validate_workdir(workdir: str) -> None:
    """只允许 /workspace 或其后代，拒绝宿主路径和任意 parent traversal。"""
    if (
        not isinstance(workdir, str)
        or not workdir
        or "\\" in workdir
        or (workdir != "/workspace" and not workdir.startswith("/workspace/"))
        or ".." in workdir.split("/")
    ):
        raise SandboxFailure(SandboxErrorCode.INVALID_WORKDIR, "工作目录必须位于容器 /workspace 下")


@dataclass(frozen=True, slots=True)
class SandboxCommand:
    """一次沙箱调用的容器内部命令。"""

    argv: tuple[str, ...]
    workdir: str = "/workspace"
    workspace_access: Literal["ro", "rw"] = "rw"
    env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        argv = tuple(self.argv)
        if not argv or any(not isinstance(part, str) or not part for part in argv):
            raise SandboxFailure(SandboxErrorCode.UNSUPPORTED_TOOL, "沙箱命令 argv 不能为空且必须由字符串组成")
        if self.workspace_access not in ("ro", "rw"):
            raise SandboxFailure(SandboxErrorCode.UNSUPPORTED_TOOL, "workspace_access 只能是 ro 或 rw")
        _validate_workdir(self.workdir)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in self.env.items()):
            raise SandboxFailure(SandboxErrorCode.UNSUPPORTED_TOOL, "沙箱环境变量必须是字符串键值")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "env", MappingProxyType(dict(self.env)))


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """沙箱进程结果；stdout/stderr 已由 runner 限制在工具结果预算内。"""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = False


def _decode_output(value: bytes | str) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _bound_output(stdout: bytes | str, stderr: bytes | str, limit: int) -> tuple[str, str, bool]:
    """限制合计输出长度，优先保留 stdout，再保留 stderr。"""
    out = _decode_output(stdout)
    err = _decode_output(stderr)
    limit = max(0, limit)
    if len(out) + len(err) <= limit:
        return out, err, False
    out = out[:limit]
    remaining = max(0, limit - len(out))
    return out, err[:remaining], True


def _docker_argv(command: SandboxCommand, workspace_root: Path, cidfile: Path, settings: Any) -> tuple[str, ...]:
    mount = f"type=bind,src={workspace_root},dst=/workspace,{command.workspace_access}"
    argv: list[str] = [
        str(settings.sandbox_docker_cli),
        "run",
        "--rm",
        "--network",
        "none",
        "--memory",
        str(settings.sandbox_docker_memory),
        "--cpus",
        str(settings.sandbox_docker_cpus),
        "--pids-limit",
        str(settings.sandbox_docker_pids_limit),
        "--read-only",
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,size={settings.sandbox_docker_tmpfs_mb}m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65532:65532",
        "--label",
        "libao.sandbox=true",
        "--cidfile",
        str(cidfile),
        "--mount",
        mount,
        "--workdir",
        command.workdir,
    ]
    for key, value in sorted(command.env.items()):
        argv.extend(("--env", f"{key}={value}"))
    argv.extend((str(settings.sandbox_docker_image), *command.argv))
    return tuple(argv)


def _failure_from_docker_exit(returncode: int, stderr: str) -> tuple[SandboxErrorCode, bool] | None:
    text = stderr.lower()
    daemon_markers = ("cannot connect to the docker daemon", "is the docker daemon running", "error during connect")
    if any(marker in text for marker in daemon_markers):
        return SandboxErrorCode.UNAVAILABLE, True
    image_markers = ("unable to find image", "pull access denied", "repository does not exist", "manifest unknown")
    if any(marker in text for marker in image_markers):
        return SandboxErrorCode.IMAGE_MISSING, False
    if returncode == 125:
        return SandboxErrorCode.START_FAILED, True
    return None


async def _stop_process(process: Any) -> None:
    if process is None:
        return
    if getattr(process, "returncode", None) is None:
        with suppress(Exception):
            process.kill()
    wait = getattr(process, "wait", None)
    if wait is not None:
        with suppress(Exception):
            await asyncio.wait_for(wait(), timeout=1)


def _cid(container_file: Path) -> str | None:
    try:
        value = container_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


async def _force_remove(container_id: str, settings: Any) -> None:
    try:
        process = await asyncio.create_subprocess_exec(
            str(settings.sandbox_docker_cli), "rm", "-f", container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.communicate(), timeout=5)
    except Exception:  # noqa: BLE001 - cleanup must not mask the original failure
        logger.warning("failed to remove sandbox container %s", container_id, exc_info=True)


async def run_docker_command(
    command: SandboxCommand,
    *,
    workspace_root: str,
    timeout_ms: int,
    settings: Any = None,
) -> SandboxResult:
    """执行一个一次性、禁网、仅挂载当前 workspace 的 Docker 命令。"""
    if timeout_ms < 1:
        raise SandboxFailure(SandboxErrorCode.TIMEOUT, "沙箱超时必须至少为 1ms")
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise SandboxFailure(SandboxErrorCode.INVALID_WORKDIR, "工作区根目录不存在或不是目录")

    fd, cidfile_name = tempfile.mkstemp(prefix="libao-sandbox-", suffix=".cid")
    os.close(fd)
    cidfile = Path(cidfile_name)
    process = None
    try:
        argv = _docker_argv(command, root, cidfile, settings)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise SandboxFailure(SandboxErrorCode.UNAVAILABLE, "Docker CLI 不可用", retryable=True) from exc
        except PermissionError as exc:
            raise SandboxFailure(SandboxErrorCode.START_FAILED, "Docker CLI 无法启动", retryable=True) from exc
        except OSError as exc:
            raise SandboxFailure(SandboxErrorCode.START_FAILED, f"Docker 进程启动失败: {exc}", retryable=True) from exc

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_ms / 1000)
        except TimeoutError as exc:
            await _stop_process(process)
            if container_id := _cid(cidfile):
                await _force_remove(container_id, settings)
            raise SandboxFailure(SandboxErrorCode.TIMEOUT, f"沙箱命令超时（>{timeout_ms}ms）") from exc

        stdout_text, stderr_text, truncated = _bound_output(
            stdout, stderr, int(getattr(settings, "tool_result_max_chars", 8000))
        )
        returncode = int(getattr(process, "returncode", 0) or 0)
        if returncode != 0:
            failure = _failure_from_docker_exit(returncode, stderr_text)
            if failure is not None:
                code, retryable = failure
                raise SandboxFailure(
                    code,
                    stderr_text or f"Docker 退出码 {returncode}",
                    retryable=retryable,
                    output={"exit_code": returncode, "stdout": stdout_text, "stderr": stderr_text},
                )
            raise SandboxFailure(
                SandboxErrorCode.EXIT_NONZERO,
                stderr_text or f"命令退出码 {returncode}",
                output={"exit_code": returncode, "stdout": stdout_text, "stderr": stderr_text},
            )
        return SandboxResult(
            exit_code=returncode,
            stdout=stdout_text,
            stderr=stderr_text,
            truncated=truncated,
        )
    except asyncio.CancelledError:
        await _stop_process(process)
        if container_id := _cid(cidfile):
            await _force_remove(container_id, settings)
        raise
    finally:
        with suppress(OSError):
            cidfile.unlink()
