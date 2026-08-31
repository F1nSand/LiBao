"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.lifespan import lifespan
from app.api.middleware import register_middleware
from app.api.router_registry import register_routers
from app.core.config import get_settings
from app.core.logging import setup_logging


class SPAStaticFiles(StaticFiles):
    """Serve the SPA entry point for client-side routes."""

    async def get_response(self, path: str, scope):
        from starlette.exceptions import HTTPException

        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and not path.startswith("api"):
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and not path.startswith("api"):
            response = await super().get_response("index.html", scope)
        return response


def create_app() -> FastAPI:
    """Build the app while preserving the historic public entry point."""

    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(title="Agent Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    register_middleware(app)
    register_routers(app, settings.base_url)

    # 可选静态托管：生产打包阶段可将 frontend_dist 放回源码目录；纯源码运行仅提供 API。
    dist = Path(settings.frontend_dist)
    if dist.is_dir():
        app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="frontend")

    return app
