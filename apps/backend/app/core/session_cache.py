"""临时会话工作区 TTL 清理（2026-08-25 方案 A 后置，《02》后端设计 §7.5）。

非工作区对话的文件落地在 ~/.LiBao/cache/sessions/<conv_id>/（见 chat.py `_session_workspace`），
不清理会无限堆积。启动时清一次 + 周期扫描，删除超过 cache_ttl_days 未改动的会话目录。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from uuid import UUID

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_LOOP_INTERVAL_S = 3600  # 周期扫描间隔（小时级，个人量级足够）


def remove_session_workspace(conversation_id: UUID | str, settings: Settings | None = None) -> bool:
    """删除一个普通会话的精确临时目录；拒绝符号链接/越出 sessions 根的路径。"""
    settings = settings or get_settings()
    sessions = (Path(settings.cache_dir) / "sessions").resolve()
    target = (sessions / str(conversation_id)).resolve()
    if target.parent != sessions or not target.is_dir():
        return False
    try:
        shutil.rmtree(target)
    except OSError as exc:
        logger.warning("删除会话临时工作区失败 %s: %s", target, exc)
        return False
    return True


def purge_stale_session_workspaces(settings: Settings | None = None, now: float | None = None) -> int:
    """删除 cache/sessions/ 下超过 cache_ttl_days 未改动的会话临时目录；返回删除数。

    以目录 mtime 为「最后活动」近似（目录在文件增删时更新；改文件内容不改目录 mtime——
    对生成后即取的 docx 场景足够，个人量级无需精确到文件级）。
    """
    settings = settings or get_settings()
    root = Path(settings.cache_dir) / "sessions"
    if not root.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - settings.cache_ttl_days * 86400
    removed = 0
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            try:
                shutil.rmtree(child)
                removed += 1
            except OSError as exc:
                logger.warning("清理临时会话工作区失败 %s: %s", child, exc)
    return removed


async def session_cache_loop(settings: Settings, interval_s: int = _LOOP_INTERVAL_S) -> None:
    """后台周期清理：启动即清一次，之后每 interval_s 清一次（永不退出，lifespan cancel 结束）。"""
    while True:
        try:
            removed = await asyncio.to_thread(purge_stale_session_workspaces, settings)
            if removed:
                logger.info("TTL 清理：删除 %d 个过期临时会话工作区", removed)
        except Exception as exc:  # noqa: BLE001  周期任务不能因单次异常退出
            logger.warning("TTL 清理异常: %s", exc)
        await asyncio.sleep(interval_s)
