"""当前 shell 后端的进程内快照（由沙箱设置服务在启动/切换时同步）。"""

from __future__ import annotations

from typing import Literal

ShellMode = Literal["powershell", "git_bash", "docker"]

_mode: ShellMode = "powershell"


def get_shell_mode() -> ShellMode:
    return _mode


def set_shell_mode(mode: ShellMode) -> None:
    global _mode
    if mode not in ("powershell", "git_bash", "docker"):
        raise ValueError(f"unsupported shell mode: {mode}")
    _mode = mode
