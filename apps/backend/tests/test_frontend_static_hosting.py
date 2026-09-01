"""FastAPI SPA hosting contract for the no-Nginx local release path."""

from __future__ import annotations

from types import SimpleNamespace

import httpx

from app.api import factory
from app.core import config


async def _request_app(app, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_default_frontend_dist_is_backend_relative_not_cwd_relative(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_LIB", str(tmp_path / "empty-user-data"))
    unrelated = tmp_path / "unrelated-working-directory"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    settings = config.Settings()

    assert (tmp_path / "empty-user-data" / "settings.json").exists() is False
    assert config.Path(settings.frontend_dist) == config.Path(config.__file__).resolve().parents[2] / "frontend_dist"


async def test_fastapi_serves_spa_root_and_deep_routes(tmp_path, monkeypatch):
    dist = tmp_path / "frontend_dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>libao-spa</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("window.__libao = true", encoding="utf-8")
    settings = SimpleNamespace(log_level="INFO", base_url="/api/v1", frontend_dist=str(dist))
    monkeypatch.setattr(factory, "get_settings", lambda: settings)

    app = factory.create_app()
    root = await _request_app(app, "/")
    deep = await _request_app(app, "/workspace/demo")
    asset = await _request_app(app, "/assets/app.js")

    assert root.status_code == 200 and "libao-spa" in root.text
    assert deep.status_code == 200 and "libao-spa" in deep.text
    assert asset.status_code == 200 and "window.__libao" in asset.text


async def test_api_routes_are_not_swallowed_by_spa(tmp_path, monkeypatch):
    dist = tmp_path / "frontend_dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>libao-spa</html>", encoding="utf-8")
    settings = SimpleNamespace(log_level="INFO", base_url="/api/v1", frontend_dist=str(dist))
    monkeypatch.setattr(factory, "get_settings", lambda: settings)

    app = factory.create_app()
    health = await _request_app(app, "/api/v1/system/health")
    missing = await _request_app(app, "/api/v1/not-present")

    assert health.status_code == 200
    assert health.headers["content-type"].startswith("application/json")
    assert "libao-spa" not in health.text
    assert missing.status_code == 404
    assert "libao-spa" not in missing.text
