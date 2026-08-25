"""首启动自动迁移：项目根数据（.agent/data/kb/uploads）→ ~/.LiBao（2026-08-25，幂等）。

打包后源码只读、数据全在用户全局目录。本模块在 init_runtime 首启时检测旧布局并复制到
~/.LiBao（copy 不删旧数据，可回滚；迁移完成写 .migrated 标记，重跑幂等跳过）。
可 CLI 手动跑：`uv run python -m app.core.migrate`。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from app.core.config import get_settings

_MARKER = ".migrated"


def _project_root() -> Path:
    """项目源码根（本文件在 app/core/ → 上两级）。"""
    return Path(__file__).resolve().parents[2]


def _copy_tree(src: Path, dst: Path) -> bool:
    """复制文件/目录到目标（覆盖已存在目标，保幂等）。返回是否执行了复制。"""
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return True


def _rewrite_workspaces_root(lib: Path) -> None:
    """workspaces.json 的 root_path：旧 data/workspaces/xxx → ~/.LiBao/workspaces/xxx（内容已随迁移复制）。"""
    ws_file = lib / "workspaces.json"
    if not ws_file.exists():
        return
    try:
        data = json.loads(ws_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    items = data.get("items", {}) if isinstance(data, dict) else {}
    new_root = str((lib / "workspaces").resolve())
    changed = False
    for row in items.values():
        rp = row.get("root_path", "")
        if "data/workspaces" in rp.replace("\\", "/"):
            row["root_path"] = str(Path(new_root) / Path(rp).name)
            changed = True
    if changed:
        ws_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _migrate_env_to_settings(lib: Path, env_file: Path) -> None:
    """项目根 .env → ~/.LiBao/settings.json（首启一次，幂等）。

    非路径配置（API key/模型等）转 snake_case 写入；路径字段显式写 ~/.LiBao 绝对路径，
    覆盖 .env 的相对路径（如 UPLOAD_DIR=uploads），保证数据落在用户全局目录。
    """
    settings_json = lib / "settings.json"
    if settings_json.exists() or not env_file.exists():
        return
    data: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().lower()  # UPPER_ENV → snake_case
        val = val.strip()
        if val and not key.endswith(("_dir", "_root")):
            data[key] = val
    # 路径字段：显式 ~/.LiBao 绝对路径（覆盖 .env 相对路径，数据在用户目录）
    data.setdefault("agent_data_dir", str(lib))
    data.setdefault("kb_root", str(lib / "kb"))
    data.setdefault("workspaces_root", str(lib / "workspaces"))
    data.setdefault("upload_dir", str(lib / "uploads"))
    data.setdefault("skills_root", str(lib / "skills"))
    lib.mkdir(parents=True, exist_ok=True)
    settings_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def migrate_to_libao(settings: Any = None) -> bool:
    """迁移项目根旧数据到 settings.agent_data_dir（默认 ~/.LiBao）。返回是否执行（幂等）。"""
    settings = settings or get_settings()
    lib = Path(settings.agent_data_dir)  # ~/.LiBao（绝对路径）
    if (lib / _MARKER).exists():
        return False
    root = _project_root()
    moved = False
    # ① 核心数据 .agent/* → ~/.LiBao/
    legacy_agent = root / ".agent"
    if legacy_agent.is_dir():
        lib.mkdir(parents=True, exist_ok=True)
        for item in legacy_agent.iterdir():
            _copy_tree(item, lib / item.name)
        moved = True
    # ② 工作区 / 知识库 / 附件
    moved = _copy_tree(root / "data" / "workspaces", lib / "workspaces") or moved
    moved = _copy_tree(root / "kb", lib / "kb") or moved
    moved = _copy_tree(root / "uploads", lib / "uploads") or moved
    if not moved:
        return False  # 无旧数据，不迁移不标记（全新安装）
    # ③ 重写 workspaces root_path（旧布局 → 新）
    _rewrite_workspaces_root(lib)
    # ④ .env 配置 → settings.json（路径字段绝对化覆盖 .env 相对路径）
    _migrate_env_to_settings(lib, root / ".env")
    # 标记迁移（幂等；确认后用户可手动删旧 .agent/data/kb/uploads）
    lib.mkdir(parents=True, exist_ok=True)
    (lib / _MARKER).write_text("migrated", encoding="utf-8")
    return True


def main() -> None:
    """CLI：uv run python -m app.core.migrate"""
    done = migrate_to_libao()
    print("migrated to ~/.LiBao" if done else "no migration needed (already at ~/.LiBao)")


if __name__ == "__main__":
    main()
