"""沙箱模式设置服务契约测试。"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.errors import ERR_SANDBOX_UNAVAILABLE, AppError
from app.services.sandbox import SandboxService
from app.storage.file.store import FileStore
from app.storage.models.user import User
from app.tools.shell_state import get_shell_mode


def _settings(tmp_path):
    return SimpleNamespace(
        agent_data_dir=str(tmp_path / "agent"),
        kb_root=str(tmp_path / "kb"),
        bash_review_enabled=True,
        bash_review_endpoint="https://review.example/v1/chat/completions",
        bash_review_model="review",
        sandbox_docker_cli="docker",
        sandbox_docker_image="libao-sandbox:latest",
    )


@pytest.mark.asyncio
async def test_sandbox_mode_persists_and_syncs_runtime(monkeypatch, tmp_path):
    import app.services.sandbox as module

    monkeypatch.setattr(module, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        module,
        "probe_backends",
        lambda: {
            "powershell": {"available": True, "detail": "ok"},
            "git_bash": {"available": True, "detail": "ok"},
            "docker": {"available": False, "detail": "missing"},
        },
    )
    store = FileStore(_settings(tmp_path))
    await store.init()
    user = User(username="admin", name="Admin", role="admin", org_id=uuid.UUID(int=1))
    async with store.session() as db:
        service = SandboxService()
        initial = await service.get(db, user)
        assert initial["mode"] == "powershell"
        saved = await service.set_mode(db, user, "git_bash")
        assert saved["mode"] == "git_bash"
        await service.sync_runtime(db, user.org_id)
        assert get_shell_mode() == "git_bash"
    module.set_shell_mode("powershell")


@pytest.mark.asyncio
async def test_sandbox_mode_rejects_unavailable_without_persisting(monkeypatch, tmp_path):
    import app.services.sandbox as module

    monkeypatch.setattr(module, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        module,
        "probe_backends",
        lambda: {mode: {"available": mode == "powershell", "detail": "missing"} for mode in module.VALID_MODES},
    )
    store = FileStore(_settings(tmp_path))
    await store.init()
    user = User(username="admin", name="Admin", role="admin", org_id=uuid.UUID(int=1))
    async with store.session() as db:
        with pytest.raises(AppError) as exc:
            await SandboxService().set_mode(db, user, "docker")
        assert exc.value.code == ERR_SANDBOX_UNAVAILABLE
        assert (await SandboxService().get(db, user))["mode"] == "powershell"
