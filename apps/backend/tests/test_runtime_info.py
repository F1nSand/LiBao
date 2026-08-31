from __future__ import annotations

from app.core.runtime_info import runtime_info


def test_runtime_info_exposes_safe_identity_and_codec():
    info = runtime_info()
    assert info["pid"] > 0
    assert info["instance_id"]
    assert "/" not in info["instance_id"]
    assert info["checkpoint_codec"] == "langgraph-typed-v1"
    assert isinstance(info["restart_required"], bool)
