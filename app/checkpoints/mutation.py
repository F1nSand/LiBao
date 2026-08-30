"""Fail-closed workspace mutation gateway used by AI direct file tools."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

from app.checkpoints.runtime import get_checkpoint_service
from app.core.config import get_settings
from app.tools.context import CheckpointToolContext, get_tool_checkpoint
from app.tools.filesystem import resolve_workspace_path

_PATH_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(path: Path) -> asyncio.Lock:
    return _PATH_LOCKS.setdefault(str(path), asyncio.Lock())


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".agent-mutation.tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class WorkspaceMutationGateway:
    def __init__(self, context: CheckpointToolContext | None = None) -> None:
        self.context = context or get_tool_checkpoint()

    @property
    def enabled(self) -> bool:
        return self.context is not None

    def _target(self, relative_path: str) -> tuple[Path, str]:
        if self.context is None:
            raise RuntimeError("AI checkpoint context 未设置")
        target = resolve_workspace_path(self.context.workspace_root, relative_path)
        rel = target.relative_to(Path(self.context.workspace_root)).as_posix()
        return target, rel

    async def write_bytes(self, relative_path: str, content: bytes, *, tool_call_id: str | None = None) -> None:
        if self.context is None:
            target = Path(relative_path)
            _write_atomic(target, content)
            return
        target, rel = self._target(relative_path)
        async with _lock_for(target):
            store_service = get_checkpoint_service(
                get_settings().agent_data_dir, get_settings().checkpoint_retention_days
            )
            store = store_service.store
            before = target.read_bytes() if target.is_file() else None
            after_sha = hashlib.sha256(content).hexdigest()
            if before is None:
                await store.prepare_missing_file(
                    self.context.conversation_id,
                    self.context.checkpoint_id,
                    rel,
                    tool_call_id=tool_call_id or self.context.tool_call_id,
                    planned_after_sha256=after_sha,
                    planned_after_exists=True,
                )
            else:
                await store.prepare_file(
                    self.context.conversation_id,
                    self.context.checkpoint_id,
                    rel,
                    before,
                    tool_call_id=tool_call_id or self.context.tool_call_id,
                    planned_after_sha256=after_sha,
                    planned_after_exists=True,
                )
            try:
                _write_atomic(target, content)
            except BaseException:
                current = target.read_bytes() if target.is_file() else None
                await store.finalize_file(
                    self.context.conversation_id,
                    self.context.checkpoint_id,
                    rel,
                    final_after_sha256=hashlib.sha256(current).hexdigest() if current is not None else None,
                    final_after_exists=current is not None,
                    status="failed",
                )
                raise
            await store.finalize_file(
                self.context.conversation_id,
                self.context.checkpoint_id,
                rel,
                final_after_sha256=after_sha,
                final_after_exists=True,
                status="applied",
            )

    async def delete_file(self, relative_path: str, *, tool_call_id: str | None = None) -> None:
        if self.context is None:
            Path(relative_path).unlink(missing_ok=True)
            return
        target, rel = self._target(relative_path)
        async with _lock_for(target):
            if not target.is_file():
                return
            store_service = get_checkpoint_service(
                get_settings().agent_data_dir, get_settings().checkpoint_retention_days
            )
            store = store_service.store
            await store.prepare_file(
                self.context.conversation_id,
                self.context.checkpoint_id,
                rel,
                target.read_bytes(),
                tool_call_id=tool_call_id or self.context.tool_call_id,
                planned_after_sha256=None,
                planned_after_exists=False,
            )
            try:
                target.unlink()
            except BaseException:
                await store.finalize_file(
                    self.context.conversation_id,
                    self.context.checkpoint_id,
                    rel,
                    final_after_sha256=hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None,
                    final_after_exists=target.is_file(),
                    status="failed",
                )
                raise
            await store.finalize_file(
                self.context.conversation_id,
                self.context.checkpoint_id,
                rel,
                final_after_sha256=None,
                final_after_exists=False,
                status="applied",
            )


def get_workspace_mutation_gateway() -> WorkspaceMutationGateway:
    return WorkspaceMutationGateway()
