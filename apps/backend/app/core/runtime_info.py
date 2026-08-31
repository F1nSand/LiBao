"""Runtime identity and stale-source detection for local health checks."""

from __future__ import annotations

import hashlib
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_STARTED_AT = datetime.now(UTC)
_STARTED_NS = time.time_ns()
_SOURCE_MTIME_NS = max((p.stat().st_mtime_ns for p in (_ROOT / "app").rglob("*.py") if p.is_file()), default=0)
_INSTANCE_ID = hashlib.sha256(str(_ROOT).casefold().replace("\\", "/").encode()).hexdigest()[:16]


def runtime_info() -> dict[str, Any]:
    current = max((p.stat().st_mtime_ns for p in (_ROOT / "app").rglob("*.py") if p.is_file()), default=0)
    return {
        "pid": os.getpid(),
        "started_at": _STARTED_AT.isoformat(),
        "instance_id": _INSTANCE_ID,
        "source_mtime_ns": _SOURCE_MTIME_NS,
        "restart_required": current > _STARTED_NS and current > _SOURCE_MTIME_NS,
        "checkpoint_codec": "langgraph-typed-v1",
    }
