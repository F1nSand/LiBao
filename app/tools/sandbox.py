"""沙盒分级（docs 01 §7.3 D1）。M1 只用 none（本地进程）；docker/microvm 为 M2 接缝，抛 NotImplementedError。"""

from __future__ import annotations

import enum
from typing import Any


class SandboxLevel(enum.StrEnum):
    NONE = "none"
    DOCKER = "docker"
    MICROVM = "microvm"


def run_in_sandbox(level: SandboxLevel, code: Any, **kwargs: Any) -> Any:
    """M1：none 直接在本地进程执行 callable；隔离级别一律未实现（M2）。"""
    if level == SandboxLevel.NONE:
        if not callable(code):
            raise TypeError("none 沙盒需要一个可调用对象")
        return code(**kwargs)
    raise NotImplementedError(f"沙盒级别 {level.value} 尚未实现（M2 接缝）")
