"""Central registry for the public HTTP routers."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routers import (
    attachments,
    chat,
    checkpoints,
    conversations,
    kb,
    memory,
    notifications,
    skills,
    system,
    tasks,
    tools,
    workspaces,
)
from app.api.routers import settings as settings_router


def register_routers(app: FastAPI, prefix: str) -> None:
    """Register routers without changing their prefixes or route contracts."""

    for router in (
        conversations.router,
        checkpoints.router,
        chat.router,
        tools.router,
        tasks.router,
        memory.router,
        kb.router,
        attachments.router,
        notifications.router,
        settings_router.router,
        system.router,
        skills.router,
        workspaces.router,
    ):
        app.include_router(router, prefix=prefix)
