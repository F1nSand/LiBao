"""Compatibility entry point for ``app.api.main:app``.

The application is assembled by :mod:`app.api.factory`; this module remains
the supported Uvicorn/FastAPI import target for existing users and scripts.
"""

from __future__ import annotations

from app.api.factory import create_app

app = create_app()

__all__ = ["app", "create_app"]
