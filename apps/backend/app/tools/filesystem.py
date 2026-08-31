"""工作区文件系统安全（M7-B，《02》后端设计 §7.8 ①）：路径强限制——realpath 必须落在 root 内。

无容器沙箱下的硬边界：read/write/edit/glob/grep 的所有路径参数先经此校验，逃逸拒绝。
"""

from __future__ import annotations

from pathlib import Path

from app.core.errors import ERR_WORKSPACE_PATH_FORBIDDEN, AppError


def resolve_workspace_path(root: str | Path, rel: str) -> Path:
    """解析相对路径并强制落在 root 内（realpath 防 .. / 符号链接逃逸；绝对路径被归一进 root 判越界）。"""
    root_p = Path(root).resolve()
    target = (root_p / rel).resolve() if rel else root_p
    if target != root_p and not target.is_relative_to(root_p):
        raise AppError(ERR_WORKSPACE_PATH_FORBIDDEN, "路径越出工作区范围")
    return target
