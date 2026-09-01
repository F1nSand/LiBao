from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".artifacts" / "release"
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")
RELEASE_README = """# LiBao 本地单用户发布包

这是 LiBao 的本地单用户发布包，默认绑定 `127.0.0.1`，固定本地用户为 `admin`。
不支持公网部署、多用户认证或把此包直接暴露到互联网。

## 启动

1. 安装 Python 3.12+、[uv](https://docs.astral.sh/uv/)。
2. 将 `settings.example.json` 复制为 `~/.LiBao/settings.json`，按需填写 LLM 配置。
3. 在本目录执行：

   ```text
   cd backend
   uv sync --frozen
   ```

4. Windows 执行 `backend\\start.cmd`；Linux/macOS 执行 `backend/start.sh`。
   API 和 SPA 都由 `http://127.0.0.1:8000` 提供。

运行数据只写入 `~/.LiBao`；请不要提交或分享该目录。
"""


def validate_version(value: str) -> str:
    """Return a safe release label that cannot escape the artifacts directory."""
    if not _VERSION_RE.fullmatch(value):
        raise ValueError("version must match ^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")
    return value


def release_paths(version: str) -> tuple[Path, Path]:
    """Resolve release paths and prove both are direct children of ARTIFACTS."""
    safe_version = validate_version(version)
    artifacts = ARTIFACTS.resolve()
    stage = (ARTIFACTS / f"libao-{safe_version}").resolve()
    archive = (ARTIFACTS / f"libao-{safe_version}.zip").resolve()
    if stage.parent != artifacts or archive.parent != artifacts:
        raise ValueError("release path escaped the artifacts directory")
    return stage, archive


def required_release_files(stage: Path) -> tuple[Path, ...]:
    return (
        stage / "backend" / "frontend_dist" / "index.html",
        stage / "backend" / "scripts" / "check_backend_runtime.py",
        stage / "backend" / "scripts" / "start_backend.py",
    )


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache", "node_modules"),
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_release(version: str) -> tuple[Path, Path]:
    stage, archive = release_paths(version)
    frontend = ROOT / "apps" / "frontend"
    backend = ROOT / "apps" / "backend"

    if stage.exists():
        shutil.rmtree(stage)
    if archive.exists():
        archive.unlink()
    stage.mkdir(parents=True)

    env = dict(os.environ)
    env["VITE_USE_MOCK"] = "false"
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        raise SystemExit("需要 PATH 中存在 npm")
    subprocess.run([npm, "run", "build"], cwd=frontend, env=env, check=True)

    copy_tree(backend / "app", stage / "backend" / "app")
    (stage / "backend").mkdir(exist_ok=True)
    for name in ("pyproject.toml", "uv.lock", ".python-version", "start.cmd", "start.sh"):
        shutil.copy2(backend / name, stage / "backend" / name)
    (stage / "backend" / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        backend / "scripts" / "check_backend_runtime.py",
        stage / "backend" / "scripts" / "check_backend_runtime.py",
    )
    shutil.copy2(
        backend / "scripts" / "start_backend.py",
        stage / "backend" / "scripts" / "start_backend.py",
    )
    copy_tree(frontend / "dist", stage / "backend" / "frontend_dist")
    copy_tree(ROOT / "deploy" / "sandbox", stage / "deploy" / "sandbox")
    (stage / "README.md").write_text(RELEASE_README, encoding="utf-8")
    shutil.copy2(ROOT / "LICENSE", stage / "LICENSE")
    shutil.copy2(ROOT / "examples" / "settings.example.json", stage / "settings.example.json")

    missing = [str(path.relative_to(stage)) for path in required_release_files(stage) if not path.is_file()]
    if missing:
        raise SystemExit(f"release layout incomplete: {', '.join(missing)}")

    files = {
        str(path.relative_to(stage)).replace("\\", "/"): sha256(path)
        for path in stage.rglob("*")
        if path.is_file()
    }
    (stage / "manifest.json").write_text(
        json.dumps({"name": "LiBao", "version": version, "mode": "local-single-user", "files": files}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=stage)
    return stage, archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local single-user LiBao release package.")
    parser.add_argument("--version", default="0.1.0")
    args = parser.parse_args()
    stage, archive = build_release(args.version)
    print(f"release directory: {stage}")
    print(f"release archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
