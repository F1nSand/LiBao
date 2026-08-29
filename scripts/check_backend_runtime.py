"""Check a local backend health endpoint without killing processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def expected_instance_id() -> str:
    root = Path(__file__).resolve().parents[1]
    return hashlib.sha256(str(root).casefold().replace("\\", "/").encode()).hexdigest()[:16]


def check(url: str, expected_instance: str | None = None) -> str:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        return "absent"
    data = body.get("data") or body
    if data.get("service") != "agent-backend":
        return "foreign"
    runtime = data.get("runtime")
    if not isinstance(runtime, dict):
        return "legacy"
    if expected_instance and runtime.get("instance_id") != expected_instance:
        return "foreign"
    if runtime.get("restart_required"):
        return "stale"
    return "current"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--instance", default=expected_instance_id())
    args = parser.parse_args()
    print(check(args.url, args.instance))
