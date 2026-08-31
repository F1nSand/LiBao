from __future__ import annotations

import pytest

from app.api.routers.system import health


@pytest.mark.asyncio
async def test_health_includes_runtime_identity():
    response = await health()
    data = response["data"]
    assert data["status"] == "ok"
    assert data["service"] == "agent-backend"
    assert data["runtime"]["checkpoint_codec"] == "langgraph-typed-v1"
    assert "pid" in data["runtime"]
