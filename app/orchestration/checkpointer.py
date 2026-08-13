"""LangGraph checkpointer 封装（docs 01 §3.3，ADR-03 sessionless）。

用 langgraph-checkpoint-postgres 的 AsyncPostgresSaver（from_conn_string 异步上下文管理器），与业务同库。
注意（langgraph#2570 规避）：checkpoint 表不进 Alembic，由应用 lifespan 调 setup() 创建，
且须在 alembic upgrade head 之后执行（先建业务表提交，再建 checkpoint 表）。
"""
from __future__ import annotations

from typing import Any

from app.core.config import Settings


class PostgresCheckpointer:
    """AsyncPostgresSaver 生命周期封装（async context manager）。

    用法：async with PostgresCheckpointer(dsn) as saver: graph = build_graph(saver); ...
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.saver: Any = None
        self._ctx: Any = None

    async def __aenter__(self) -> Any:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        self._ctx = AsyncPostgresSaver.from_conn_string(self.dsn)
        self.saver = await self._ctx.__aenter__()
        await self.saver.setup()
        return self.saver

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self._ctx.__aexit__(exc_type, exc, tb)
        self.saver = None


def build_checkpointer(settings: Settings) -> PostgresCheckpointer:
    return PostgresCheckpointer(settings.sync_checkpoint_dsn)  # psycopg 驱动（剥掉 +asyncpg）
