from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.checkpoints.identity import build_workspace_identity, workspace_identity_matches


def test_build_session_identity_uses_session_scope_and_canonical_root(tmp_path: Path):
    raw_root = tmp_path / "nested" / ".." / "workspace"

    identity = build_workspace_identity(str(raw_root), None)

    expected_root = os.path.normcase(tmp_path.joinpath("workspace").resolve(strict=False).as_posix())
    assert identity == f"session:{expected_root}"


def test_build_workspace_identity_keeps_uuid_scope(tmp_path: Path):
    root = tmp_path / "workspace"

    identity = build_workspace_identity(str(root), "workspace-123")

    expected_root = os.path.normcase(root.resolve(strict=False).as_posix())
    assert identity == f"workspace-123:{expected_root}"


def test_match_accepts_legacy_none_scope_only_for_same_session_root(tmp_path: Path):
    root = tmp_path / "workspace"
    stored = f"None:{root}"

    assert workspace_identity_matches(stored, str(root), None)
    assert not workspace_identity_matches(stored, str(tmp_path / "other"), None)
    assert not workspace_identity_matches(stored, str(root), "workspace-123")
    assert not workspace_identity_matches("None:", str(root), None)
    assert not workspace_identity_matches(stored, "", None)


@pytest.mark.skipif(os.name != "nt", reason="Windows path spelling compatibility")
def test_match_tolerates_windows_case_and_separator_representation(tmp_path: Path):
    root = tmp_path / "Workspace"
    stored_root = str(root).replace("/", "\\").upper()

    assert workspace_identity_matches(f"None:{stored_root}", str(root), None)
