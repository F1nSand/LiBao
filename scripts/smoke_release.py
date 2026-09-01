from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from zipfile import ZipFile


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def extract_archive(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with ZipFile(archive) as handle:
        for member in handle.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"发布包包含越界路径: {member.filename}")
        handle.extractall(destination)
    return destination


def fetch_text(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}: {url}")
            return response.read().decode("utf-8")
    except (OSError, urllib.error.URLError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"无法访问发布包端点: {url}") from exc


def wait_for_backend(process: subprocess.Popen[bytes], base_url: str, timeout: float = 120) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(
                f"{base_url}/api/v1/system/health", timeout=2
            ) as response:
                if response.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
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


def _is_html(text: str) -> bool:
    lowered = text.lstrip().lower()
    return lowered.startswith("<!doctype html") or "<html" in lowered[:512]


def smoke_release(archive: Path) -> None:
    """Extract and boot a release archive, then verify health and SPA fallback."""

    archive = Path(archive)
    if not archive.is_file():
        raise RuntimeError(f"发布包不存在: {archive}")
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("需要 PATH 中存在 uv")

    with tempfile.TemporaryDirectory(prefix="libao-release-smoke-") as temp_root:
        temp_root_path = Path(temp_root)
        extracted = extract_archive(archive, temp_root_path / "release")
        backend = extracted / "backend"
        isolated_home = temp_root_path / "home"
        isolated_home.mkdir()
        env = dict(os.environ)
        env["HOME"] = str(isolated_home)
        env["USERPROFILE"] = str(isolated_home)
        env["LIBAO_BACKEND_PORT"] = str(free_loopback_port())
        port = int(env["LIBAO_BACKEND_PORT"])
        base_url = f"http://127.0.0.1:{port}"

        subprocess.run([uv, "sync", "--frozen"], cwd=backend, env=env, check=True)
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                [uv, "run", "python", "scripts/start_backend.py", "--port", str(port)],
                cwd=backend,
                env=env,
                start_new_session=os.name != "nt",
            )
            if not wait_for_backend(process, base_url):
                raise RuntimeError("发布包后端健康检查超时或进程已退出")
            fetch_text(f"{base_url}/api/v1/system/health")
            root = fetch_text(f"{base_url}/")
            deep = fetch_text(f"{base_url}/workspace/smoke")
            if not _is_html(root) or not _is_html(deep):
                raise RuntimeError("发布包未正确提供 SPA 根路径或深层路由回退")
        finally:
            if process is not None:
                stop_process(process)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a LiBao release archive.")
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    smoke_release(args.archive)
    print(f"release smoke passed: {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
