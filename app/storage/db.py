"""异步数据库引擎与会话工厂（docs 01 §2 storage/db.py）。

引擎/会话工厂在应用 lifespan 创建后挂到 app.state；Alembic 用同一 URL（剥 asyncpg 前缀）。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings

# sessionmaker 桥（M3）：工具层（kb_search）在五层约束下直连存储层建独立会话。
# lifespan 在 init_db 后 set_sessionmaker；未设置时 get 返回 None（调用方静默降级）。
_sessionmaker: Any = None


def set_sessionmaker(sm: Any) -> None:
    global _sessionmaker
    _sessionmaker = sm


def get_sessionmaker() -> Any:
    return _sessionmaker


def init_db(settings: Settings | None = None) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    settings = settings or get_settings()
    engine: AsyncEngine = create_async_engine(settings.database_url, echo=settings.debug)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, sessionmaker
