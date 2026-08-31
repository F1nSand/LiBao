"""Process-local accessors for the code checkpoint store/service."""

from __future__ import annotations

from functools import lru_cache

from app.checkpoints.service import CheckpointService
from app.checkpoints.store import CodeCheckpointStore


@lru_cache(maxsize=4)
def get_checkpoint_service(data_root: str, retention_days: int) -> CheckpointService:
    """Share one store/lock set per configured data root across requests."""
    return CheckpointService(CodeCheckpointStore(data_root), retention_days=retention_days)
