from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
CommandRunner = Callable[..., object]


def resolve_npm(which: Callable[[str], str | None]) -> str | None:
    return which("npm.cmd") or which("npm")


def run_bootstrap(*, which: Callable[[str], str | None] = shutil.which, run: CommandRunner = subprocess.run) -> int:
    uv = which("uv")
    npm = resolve_npm(which)
    if not uv or not npm:
        print("需要 PATH 中存在 uv 和 npm")
        return 2
    commands = (
        [uv, "sync", "--project", "apps/backend"],
        [uv, "sync", "--project", "tools/devpanel"],
        [npm, "ci", "--prefix", "apps/frontend"],
    )
    for command in commands:
        result = run(command, cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    return 0


def main() -> int:
    return run_bootstrap()


if __name__ == "__main__":
    raise SystemExit(main())
