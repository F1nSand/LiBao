from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "apps" / "backend"
FRONTEND = ROOT / "apps" / "frontend"
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_FRONTEND_URL = "http://127.0.0.1:5173"


def parse_loopback_url(value: str, default_port: int) -> tuple[str, int, str]:
    """Validate and normalize a local HTTP URL used by the real E2E runner."""

    if not 1 <= default_port <= 65535:
        raise ValueError(f"端口无效: {default_port}")
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
        raise ValueError("真实 E2E 只允许使用 http://127.0.0.1[:port]")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("真实 E2E URL 不允许包含凭据")
    if parsed.query or parsed.fragment:
        raise ValueError("真实 E2E URL 不允许包含 query 或 fragment")
    if parsed.path.rstrip("/"):
        raise ValueError("真实 E2E URL 不允许包含路径")
    try:
        port = default_port if parsed.port is None else parsed.port
    except ValueError as exc:
        raise ValueError("真实 E2E URL 的端口无效") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"端口无效: {port}")
    return parsed.hostname, port, f"http://127.0.0.1:{port}"


def healthy(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(
            f"{base_url}/api/v1/system/health", timeout=2
        ) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def wait_for_backend(
    process: subprocess.Popen[bytes], base_url: str, timeout: float = 120
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if healthy(base_url):
            return True
        if process.poll() is not None:
            return False
        time.sleep(2)
    return healthy(base_url)


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


def run_real_e2e(argv: Sequence[str]) -> int:
    try:
        _, backend_port, backend_url = parse_loopback_url(
            os.environ.get("E2E_BACKEND_URL", DEFAULT_BACKEND_URL), 8000
        )
        _, _, frontend_url = parse_loopback_url(
            os.environ.get("E2E_FRONTEND_URL", DEFAULT_FRONTEND_URL), 5173
        )
        frontend_port = int(urlsplit(frontend_url).port or 5173)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    uv = shutil.which("uv")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not uv or not npm:
        print("需要 PATH 中存在 uv 和 npm", file=sys.stderr)
        return 2

    backend: subprocess.Popen[bytes] | None = None
    try:
        if not healthy(backend_url):
            backend = subprocess.Popen(
                [
                    uv,
                    "run",
                    "uvicorn",
                    "app.api.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(backend_port),
                ],
                cwd=BACKEND,
            )
            if not wait_for_backend(backend, backend_url):
                print("后端健康检查超时或进程已退出", file=sys.stderr)
                return 1

        env = dict(os.environ)
        env["E2E_BACKEND_URL"] = backend_url
        env["E2E_FRONTEND_URL"] = frontend_url
        env["VITE_API_PROXY"] = backend_url
        env["VITE_USE_MOCK"] = "false"
        command = [npm, "run", "test:e2e:real", "--", *argv]
        return subprocess.run(command, cwd=FRONTEND, env=env).returncode
    finally:
        if backend is not None:
            stop_process(backend)


if __name__ == "__main__":
    raise SystemExit(run_real_e2e(sys.argv[1:]))
