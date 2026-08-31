from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "apps" / "backend"
FRONTEND = ROOT / "apps" / "frontend"
BACKEND_URL = os.environ.get("E2E_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")


def healthy() -> bool:
    try:
        with urllib.request.urlopen(f"{BACKEND_URL}/api/v1/system/health", timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    uv = shutil.which("uv")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not uv or not npm:
        print("需要 PATH 中存在 uv 和 npm", file=sys.stderr)
        return 2

    backend: subprocess.Popen[bytes] | None = None
    try:
        if not healthy():
            backend = subprocess.Popen(
                [uv, "run", "uvicorn", "app.api.main:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=BACKEND,
            )
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline and not healthy():
                if backend.poll() is not None:
                    print(f"后端启动失败，exit={backend.returncode}", file=sys.stderr)
                    return backend.returncode or 1
                time.sleep(2)
            if not healthy():
                print("后端健康检查超时", file=sys.stderr)
                return 1

        env = dict(os.environ)
        env["E2E_BACKEND_URL"] = BACKEND_URL
        env.setdefault("E2E_FRONTEND_URL", "http://127.0.0.1:5173")
        command = [npm, "run", "test:e2e:real", "--", *sys.argv[1:]]
        return subprocess.run(command, cwd=FRONTEND, env=env).returncode
    finally:
        if backend is not None:
            stop_process(backend)


if __name__ == "__main__":
    raise SystemExit(main())
