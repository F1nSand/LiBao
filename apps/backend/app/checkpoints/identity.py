"""Canonical workspace identity used by checkpoint creation and restore."""

from __future__ import annotations

import os
from pathlib import Path


def _canonical_root(root: str) -> str:
    """Return a stable, platform-neutral spelling for a workspace root."""

    if not str(root).strip():
        raise ValueError("workspace root 不能为空")
    resolved = Path(root).expanduser().resolve(strict=False)
    return os.path.normcase(resolved.as_posix())


def build_workspace_identity(workspace_root: str, workspace_id: str | None = None) -> str:
    """Build the identity persisted in a checkpoint manifest."""

    scope = str(workspace_id) if workspace_id else "session"
    return f"{scope}:{_canonical_root(workspace_root)}"


def workspace_identity_matches(
    stored_identity: str,
    workspace_root: str,
    workspace_id: str | None = None,
) -> bool:
    """Compare a stored identity without weakening root isolation.

    Older ordinary-session manifests used ``None:<root>``.  That spelling is
    accepted only for a session restore and only when the canonical roots are
    identical; real workspace identities still require an exact workspace id.
    """

    if not stored_identity:
        return False
    scope, separator, stored_root = stored_identity.partition(":")
    if not separator or not stored_root.strip():
        return False
    try:
        current = _canonical_root(workspace_root)
        stored = _canonical_root(stored_root)
    except (TypeError, ValueError, OSError):
        return False
    if stored != current:
        return False
    if workspace_id:
        return scope == str(workspace_id)
    return scope in {"session", "None"}
