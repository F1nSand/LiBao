"""沙箱运行契约（docs 01 §7.3 D1）。

命令只携带容器内部路径；实际 Docker 进程边界由后续 runner 负责。NONE 保持宿主执行，
DOCKER/MICROVM 的级别可被配置和持久化，其中 MICROVM 暂不提供执行实现。
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal


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
        output: dict | None = None,
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
