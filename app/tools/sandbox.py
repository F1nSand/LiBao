"""沙箱运行契约（docs 01 §7.3 D1）。

命令只携带工作区相对路径；WORKSPACE 由本模块的宿主 shell runner 执行，DOCKER
由一次性容器 runner 执行，NONE 保持普通 handler。DOCKER/MICROVM 的级别可被配置和持久化，
其中 MICROVM 暂不提供执行实现。
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

logger = logging.getLogger(__name__)
_CLEANUP_TIMEOUT_S = 5.0


class SandboxLevel(enum.StrEnum):
    NONE = "none"
    WORKSPACE = "workspace"
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
    CONFIRM_REQUIRED = "sandbox_confirmation_required"
    POLICY_BLOCKED = "sandbox_policy_blocked"


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
class WorkspaceCommand:
    """宿主工作区轻隔离命令计划。

    `script` 通过 stdin 传给服务端选定的 shell；模型不能注入宿主可执行文件、cwd
    或环境变量。`workdir` 始终是相对工作区路径，和 Docker 命令的 `/workspace/...`
    约束保持同一语义。
    """

    script: str
    shell: Literal["powershell", "git_bash"] = "powershell"
    workdir: str = "."
    env: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.script, str) or not self.script.strip():
            raise SandboxFailure(SandboxErrorCode.UNSUPPORTED_TOOL, "宿主 shell 脚本不能为空")
        if self.shell not in ("powershell", "git_bash"):
            raise SandboxFailure(SandboxErrorCode.UNSUPPORTED_TOOL, "宿主 shell 只能是 powershell 或 git_bash")
        if not isinstance(self.workdir, str) or not self.workdir:
            raise SandboxFailure(SandboxErrorCode.INVALID_WORKDIR, "宿主 shell 工作目录不能为空")
        # Windows pathlib does not treat POSIX-style `/tmp` as absolute; reject
        # both drive/UNC and slash-rooted paths before resolving under root.
        if (
            Path(self.workdir).is_absolute()
            or self.workdir.startswith("/")
            or "\\" in self.workdir
            or ".." in self.workdir.split("/")
        ):
            raise SandboxFailure(SandboxErrorCode.INVALID_WORKDIR, "宿主 shell 工作目录必须是工作区内相对路径")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in self.env.items()):
            raise SandboxFailure(SandboxErrorCode.UNSUPPORTED_TOOL, "宿主 shell 环境变量必须是字符串键值")
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


async def _read_stream_bounded(stream: Any, max_bytes: int) -> tuple[bytes, bool]:
    """持续排空一个子进程管道，只保留有限前缀，避免管道阻塞或宿主内存膨胀。"""
    limit = max(0, int(max_bytes))
    chunks = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            break
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8", errors="replace")
        if not isinstance(chunk, bytes):
            chunk = bytes(chunk)
        before = len(chunks)
        if before < limit:
            chunks.extend(chunk[: limit - before])
        if len(chunk) > max(0, limit - before):
            truncated = True
    return bytes(chunks), truncated


async def _communicate_bounded(process: Any, limit_chars: int) -> tuple[bytes, bytes, bool]:
    """并发 drain stdout/stderr 并等待进程结束，内存上限按字符预算换算为 UTF-8 字节。"""
    per_stream_limit = max(65536, max(0, int(limit_chars)) * 4)
    stdout_task = asyncio.create_task(_read_stream_bounded(process.stdout, per_stream_limit))
    stderr_task = asyncio.create_task(_read_stream_bounded(process.stderr, per_stream_limit))
    wait_task = asyncio.create_task(process.wait())
    try:
        (stdout, stdout_truncated), (stderr, stderr_truncated), _ = await asyncio.gather(
            stdout_task, stderr_task, wait_task
        )
        return stdout, stderr, stdout_truncated or stderr_truncated
    except BaseException:
        for task in (stdout_task, stderr_task, wait_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(stdout_task, stderr_task, wait_task, return_exceptions=True)
        raise


_WORKSPACE_ENV_KEYS = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_ARCHITEW6432",
    "LANG",
    "LC_ALL",
    "TERM",
)
_GIT_BASH_CANDIDATES = (
    "C:/Program Files/Git/usr/bin/bash.exe",
    "C:/Program Files/Git/bin/bash.exe",
    "C:/Program Files (x86)/Git/bin/bash.exe",
)


def _workspace_shell_executable(shell: str) -> str | None:
    """只选择服务端已知的 shell，不接受命令文本提供的可执行文件路径。"""
    if shell == "powershell":
        candidates = (
            "C:/Program Files/PowerShell/7/pwsh.exe",
            "C:/Program Files/PowerShell/7-preview/pwsh.exe",
        )
        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate
        return shutil.which("pwsh")
    for candidate in _GIT_BASH_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    return None


def _workspace_environment(root: Path, overrides: Mapping[str, str]) -> dict[str, str]:
    """构造最小宿主环境，并把用户级目录收拢到当前工作区运行目录。"""
    runtime = root / ".agent" / "runtime"
    home = runtime / "home"
    temp = runtime / "tmp"
    cache = runtime / "cache"
    for path in (home, temp, cache):
        path.mkdir(parents=True, exist_ok=True)
    env = {key: value for key in _WORKSPACE_ENV_KEYS if (value := os.environ.get(key))}
    env.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "TEMP": str(temp),
            "TMP": str(temp),
            "NPM_CONFIG_CACHE": str(cache / "npm"),
            "PIP_CACHE_DIR": str(cache / "pip"),
            "UV_CACHE_DIR": str(cache / "uv"),
        }
    )
    # 仅允许服务端注入的内部元数据，拒绝将模型输入变成任意环境变量。
    if "LIBAO_SHELL_REVIEW_NOTE" in overrides:
        env["LIBAO_SHELL_REVIEW_NOTE"] = overrides["LIBAO_SHELL_REVIEW_NOTE"]
    return env


def _attach_windows_job(pid: int) -> tuple[Any, Any] | None:
    """为宿主命令绑定 kill-on-close Job Object；无 pywin32 时由 taskkill 兜底。"""
    if sys.platform != "win32":
        return None
    try:
        import win32api
        import win32con
        import win32job

        job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
        process_handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, pid)
        win32job.AssignProcessToJobObject(job, process_handle)
        return job, process_handle
    except Exception:  # noqa: BLE001 - fallback cleanup remains available
        return None


def _close_windows_job(job_handles: tuple[Any, Any] | None) -> None:
    if job_handles is None:
        return
    try:
        import win32api

        for handle in job_handles:
            win32api.CloseHandle(handle)
    except Exception:  # noqa: BLE001 - cleanup must not mask command result
        logger.debug("failed to close shell Job Object", exc_info=True)


async def _taskkill_tree(pid: int) -> None:
    """Job Object 不可用时的 Windows 进程树兜底清理。"""
    if sys.platform != "win32":
        return
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(_communicate_bounded(process, 4096), timeout=_CLEANUP_TIMEOUT_S)
    except Exception:  # noqa: BLE001 - cleanup must not mask original error
        await _stop_process(process)
        logger.warning("failed to taskkill shell process tree pid=%s", pid, exc_info=True)


async def _stop_workspace_process(process: Any, job_handles: tuple[Any, Any] | None) -> None:
    if process is None:
        _close_windows_job(job_handles)
        return
    pid = getattr(process, "pid", None)
    if sys.platform == "win32":
        _close_windows_job(job_handles)
        if job_handles is None and pid:
            await _taskkill_tree(int(pid))
    else:
        if pid:
            with suppress(ProcessLookupError, OSError):
                os.killpg(int(pid), signal.SIGKILL)
    await _stop_process(process)


async def run_workspace_command(
    command: WorkspaceCommand,
    *,
    workspace_root: str,
    timeout_ms: int,
    settings: Any = None,
) -> SandboxResult:
    """在工作区策略边界内执行宿主 PowerShell/Git Bash 脚本。"""
    if timeout_ms < 1:
        raise SandboxFailure(SandboxErrorCode.TIMEOUT, "宿主 shell 超时必须至少为 1ms")
    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise SandboxFailure(SandboxErrorCode.INVALID_WORKDIR, "工作区根目录不存在或不是目录")
    target = (root / command.workdir).resolve()
    if target != root and not target.is_relative_to(root):
        raise SandboxFailure(SandboxErrorCode.INVALID_WORKDIR, "宿主 shell 工作目录越出工作区范围")
    if not target.is_dir():
        raise SandboxFailure(SandboxErrorCode.INVALID_WORKDIR, "宿主 shell 工作目录不存在或不是目录")
    executable = _workspace_shell_executable(command.shell)
    if executable is None:
        raise SandboxFailure(SandboxErrorCode.UNAVAILABLE, f"未找到 {command.shell} 可执行文件", retryable=True)
    argv = (
        (executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-")
        if command.shell == "powershell"
        else (executable, "--noprofile", "--norc", "-s")
    )
    kwargs: dict[str, Any] = {
        "stdin": asyncio.subprocess.PIPE,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "env": _workspace_environment(root, command.env),
        "cwd": str(target),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = None
    job_handles = None
    try:
        try:
            process = await asyncio.create_subprocess_exec(*argv, **kwargs)
        except FileNotFoundError as exc:
            raise SandboxFailure(
                SandboxErrorCode.UNAVAILABLE, f"未找到 {command.shell} 可执行文件", retryable=True
            ) from exc
        except PermissionError as exc:
            raise SandboxFailure(SandboxErrorCode.START_FAILED, f"{command.shell} 无法启动", retryable=True) from exc
        except OSError as exc:
            raise SandboxFailure(SandboxErrorCode.START_FAILED, f"宿主 shell 启动失败: {exc}", retryable=True) from exc
        if sys.platform == "win32" and getattr(process, "pid", None):
            job_handles = _attach_windows_job(int(process.pid))
        if process.stdin is not None:
            process.stdin.write(command.script.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
        try:
            stdout, stderr, stream_truncated = await asyncio.wait_for(
                _communicate_bounded(
                    process, int(getattr(settings, "tool_result_max_chars", 8000) if settings else 8000)
                ),
                timeout=timeout_ms / 1000,
            )
        except TimeoutError as exc:
            await _stop_workspace_process(process, job_handles)
            job_handles = None
            raise SandboxFailure(SandboxErrorCode.TIMEOUT, f"宿主 shell 命令超时（>{timeout_ms}ms）") from exc
        except asyncio.CancelledError:
            await _stop_workspace_process(process, job_handles)
            job_handles = None
            raise
        except Exception as exc:  # noqa: BLE001 - normalize pipe/runner failures
            await _stop_workspace_process(process, job_handles)
            job_handles = None
            raise SandboxFailure(
                SandboxErrorCode.START_FAILED, f"读取宿主 shell 输出失败: {exc}", retryable=True
            ) from exc
        stdout_text, stderr_text, truncated = _bound_output(
            stdout, stderr, int(getattr(settings, "tool_result_max_chars", 8000) if settings else 8000)
        )
        truncated = truncated or stream_truncated
        returncode = int(getattr(process, "returncode", 0) or 0)
        if returncode != 0:
            raise SandboxFailure(
                SandboxErrorCode.EXIT_NONZERO,
                stderr_text or f"命令退出码 {returncode}",
                output={"exit_code": returncode, "stdout": stdout_text, "stderr": stderr_text},
            )
        return SandboxResult(returncode, stdout_text, stderr_text, truncated=truncated)
    except asyncio.CancelledError:
        if process is not None:
            await _stop_workspace_process(process, job_handles)
        raise
    finally:
        if job_handles is not None:
            _close_windows_job(job_handles)


def _runtime_user() -> str:
    """在 Linux 非 root 宿主上映射当前用户，其他环境使用镜像内的非 root 用户。"""
    if not sys.platform.startswith("linux"):
        return "65532:65532"
    try:
        uid = int(os.getuid())
        gid = int(os.getgid())
    except (AttributeError, TypeError, ValueError):
        return "65532:65532"
    if uid <= 0 or gid <= 0:
        return "65532:65532"
    return f"{uid}:{gid}"


def _docker_argv(
    command: SandboxCommand,
    workspace_root: Path,
    cidfile: Path,
    container_name: str,
    settings: Any,
) -> tuple[str, ...]:
    # `rw` is the default for --mount and is not a valid bare field (Docker
    # rejects it with "invalid field 'rw'").  Only spell out read-only binds.
    mount = f"type=bind,src={workspace_root},dst=/workspace"
    if command.workspace_access == "ro":
        mount += ",readonly"
    argv: list[str] = [
        str(settings.sandbox_docker_cli),
        "run",
        "--rm",
        "--pull",
        "never",
        "--name",
        container_name,
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
        _runtime_user(),
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
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            str(settings.sandbox_docker_cli), "rm", "-f", container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(_communicate_bounded(process, 16_384), timeout=_CLEANUP_TIMEOUT_S)
    except TimeoutError:
        await _stop_process(process)
        logger.warning("timed out removing sandbox container %s", container_id)
    except Exception:  # noqa: BLE001 - cleanup must not mask the original failure
        await _stop_process(process)
        logger.warning("failed to remove sandbox container %s", container_id, exc_info=True)


async def _cleanup_container(process: Any, cidfile: Path, container_name: str, settings: Any) -> None:
    """停止 Docker CLI 后按 cidfile 或唯一名称兜底删除容器。"""
    cleanup_task = asyncio.create_task(_cleanup_container_inner(process, cidfile, container_name, settings))
    try:
        await asyncio.shield(cleanup_task)
    except asyncio.CancelledError:
        await cleanup_task


async def _cleanup_container_inner(process: Any, cidfile: Path, container_name: str, settings: Any) -> None:
    await _stop_process(process)
    await _force_remove(_cid(cidfile) or container_name, settings)


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
    container_name = f"libao-sandbox-{uuid.uuid4().hex}"
    try:
        argv = _docker_argv(command, root, cidfile, container_name, settings)
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
            stdout, stderr, stream_truncated = await asyncio.wait_for(
                _communicate_bounded(process, int(getattr(settings, "tool_result_max_chars", 8000))),
                timeout=timeout_ms / 1000,
            )
        except TimeoutError as exc:
            await _cleanup_container(process, cidfile, container_name, settings)
            raise SandboxFailure(SandboxErrorCode.TIMEOUT, f"沙箱命令超时（>{timeout_ms}ms）") from exc
        except Exception as exc:  # noqa: BLE001 - normalize pipe/runner failures
            await _cleanup_container(process, cidfile, container_name, settings)
            raise SandboxFailure(SandboxErrorCode.START_FAILED, f"读取 Docker 输出失败: {exc}", retryable=True) from exc

        stdout_text, stderr_text, truncated = _bound_output(
            stdout, stderr, int(getattr(settings, "tool_result_max_chars", 8000))
        )
        truncated = truncated or stream_truncated
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
        await _cleanup_container(process, cidfile, container_name, settings)
        raise
    finally:
        with suppress(OSError):
            cidfile.unlink()
