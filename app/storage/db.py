"""异步数据库引擎与会话工厂（docs 01 §2 storage/db.py）。

引擎/会话工厂在应用 lifespan 创建后挂到 app.state；Alembic 用同一 URL（剥 asyncpg 前缀）。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings


def init_db(settings: Settings | None = None) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    settings = settings or get_settings()
    engine: AsyncEngine = create_async_engine(settings.database_url, echo=settings.debug)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, sessionmaker
