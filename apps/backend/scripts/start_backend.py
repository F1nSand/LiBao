"""Cross-platform foreground launcher for the local single-user backend."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
for import_root in (BACKEND_ROOT, SCRIPT_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

_runtime_checker = importlib.import_module("check_backend_runtime")
check = _runtime_checker.check
expected_instance_id = _runtime_checker.expected_instance_id


HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def backend_url(port: int) -> str:
    return f"http://{HOST}:{port}/api/v1/system/health"


def _port(value: str | None) -> int:
    text = value or os.environ.get("LIBAO_BACKEND_PORT", str(DEFAULT_PORT))
    try:
        port = int(text)
    except ValueError as exc:
        raise ValueError("LIBAO_BACKEND_PORT 必须是 1 到 65535 的整数") from exc
    if not 1 <= port <= 65535:
        raise ValueError("LIBAO_BACKEND_PORT 必须是 1 到 65535 的整数")
    return port


def runtime_state(url: str) -> str:
    return check(url, expected_instance_id())


def run_uvicorn(port: int) -> None:
    import uvicorn

    uvicorn.run("app.api.main:app", host=HOST, port=port)


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("LIBAO_BACKEND_HOST", HOST) != HOST:
        raise SystemExit("后端仅允许绑定 127.0.0.1")
    parser = argparse.ArgumentParser(description="Start the local single-user LiBao backend.")
    parser.add_argument("--port", default=None)
    args = parser.parse_args(argv)
    try:
        port = _port(args.port)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    url = backend_url(port)
    state = runtime_state(url)
    if state == "current":
        print(f"后端已在 {HOST}:{port} 运行（当前项目），跳过启动")
        return 0
    if state != "absent":
        print(f"检测到后端状态={state}；不会自动复用或终止其他进程", file=sys.stderr)
        return 1
    print(f"启动后端：http://{HOST}:{port}/docs（Ctrl+C 停止）")
    run_uvicorn(port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
