from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".artifacts" / "release"


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local single-user LiBao release package.")
    parser.add_argument("--version", default="0.1.0")
    args = parser.parse_args()

    frontend = ROOT / "apps" / "frontend"
    backend = ROOT / "apps" / "backend"
    stage = ARTIFACTS / f"libao-{args.version}"
    archive = ARTIFACTS / f"libao-{args.version}.zip"

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
    copy_tree(frontend / "dist", stage / "frontend_dist")
    copy_tree(ROOT / "deploy" / "sandbox", stage / "deploy" / "sandbox")
    shutil.copy2(ROOT / "README.md", stage / "README.md")
    shutil.copy2(ROOT / "LICENSE", stage / "LICENSE")
    shutil.copy2(ROOT / "examples" / "settings.example.json", stage / "settings.example.json")

    files = {
        str(path.relative_to(stage)).replace("\\", "/"): sha256(path)
        for path in stage.rglob("*")
        if path.is_file()
    }
    (stage / "manifest.json").write_text(
        json.dumps({"name": "LiBao", "version": args.version, "mode": "local-single-user", "files": files}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    shutil.make_archive(str(archive.with_suffix("")), "zip", root_dir=stage)
    print(f"release directory: {stage}")
    print(f"release archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
