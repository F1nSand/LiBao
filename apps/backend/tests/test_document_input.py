"""计划中正文输入窄接口的回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import AppError
from app.orchestration.document_input import document_config, prepare_workspace_file_input


def test_document_config_force_context_clears_empty_state():
    assert document_config(None) == {}
    assert document_config(None, force_context=True) == {"document_context": {"index": {}, "current_ids": set()}}


@pytest.mark.asyncio
async def test_workspace_document_input_reads_only_valid_relative_files(tmp_path: Path):
    (tmp_path / "notes.md").write_text("workspace nonce", encoding="utf-8")
    result = await prepare_workspace_file_input(
        workspace_root=str(tmp_path), file_refs=[{"path": "notes.md"}], query="nonce"
    )
    assert "workspace nonce" in result.context_text
    assert "[工作区引用: notes.md" in result.context_text

    with pytest.raises(AppError) as exc:
        await prepare_workspace_file_input(workspace_root=str(tmp_path), file_refs=[{"path": "../secret"}], query="")
    assert exc.value.code == 40015


@pytest.mark.asyncio
async def test_workspace_document_input_bounds_source_reads(tmp_path: Path):
    (tmp_path / "large.txt").write_bytes(b"x" * (1_048_576 + 1))
    result = await prepare_workspace_file_input(
        workspace_root=str(tmp_path), file_refs=[{"path": "large.txt"}], query=""
    )
    assert result.context_text == ""
    assert result.omitted == ("large.txt",)
