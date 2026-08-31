"""临时会话工作区 TTL 清理测试（app/core/session_cache.py，2026-08-25 方案 A 后置）。"""
from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.session_cache import purge_stale_session_workspaces, remove_session_workspace


def _settings(cache_dir, ttl_days=7):
    return SimpleNamespace(cache_dir=str(cache_dir), cache_ttl_days=ttl_days)


def _touch(path: Path, age_s: float) -> None:
    """设置文件/目录 mtime 为 now-age_s（模拟年龄）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir() or not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    os.utime(path, (time.time() - age_s, time.time() - age_s))


def test_purge_removes_only_stale(tmp_path):
    s = _settings(tmp_path / "cache")
    sessions = tmp_path / "cache" / "sessions"
    old = sessions / "old-conv"
    fresh = sessions / "fresh-conv"
    _touch(old, age_s=8 * 86400)  # 8 天前 → 删
    _touch(fresh, age_s=1 * 86400)  # 1 天前 → 保留
    assert purge_stale_session_workspaces(s) == 1
    assert not old.exists()
    assert fresh.is_dir()


def test_purge_skips_non_dir_entries(tmp_path):
    s = _settings(tmp_path / "cache")
    sessions = tmp_path / "cache" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "readme.txt").write_text("x", encoding="utf-8")
    _touch(sessions / "old-conv", age_s=30 * 86400)
    assert purge_stale_session_workspaces(s) == 1
    assert (sessions / "readme.txt").is_file()  # 非目录条目不删


def test_purge_no_sessions_dir_returns_zero(tmp_path):
    s = _settings(tmp_path / "cache")
    assert purge_stale_session_workspaces(s) == 0


def test_purge_uses_now_override(tmp_path):
    """now 参数注入（测试不依赖真实时钟，避免边界抖动）。"""
    s = _settings(tmp_path / "cache", ttl_days=7)
    sessions = tmp_path / "cache" / "sessions"
    _touch(sessions / "a", age_s=0)
    # 把 now 拨到 8 天后 → a 过期
    assert purge_stale_session_workspaces(s, now=time.time() + 8 * 86400) == 1
    assert not (sessions / "a").exists()


def test_purge_respects_ttl_days(tmp_path):
    s = _settings(tmp_path / "cache", ttl_days=1)
    sessions = tmp_path / "cache" / "sessions"
    _touch(sessions / "two-days", age_s=2 * 86400)
    _touch(sessions / "half-day", age_s=0.5 * 86400)
    assert purge_stale_session_workspaces(s) == 1
    assert (sessions / "half-day").is_dir()
    assert not (sessions / "two-days").exists()


def test_remove_session_workspace_only_deletes_exact_session(tmp_path):
    s = _settings(tmp_path / "cache")
    sessions = tmp_path / "cache" / "sessions"
    target = sessions / "conv-1"
    target.mkdir(parents=True)
    (target / "probe").write_text("x", encoding="utf-8")
    assert remove_session_workspace("conv-1", s) is True
    assert not target.exists()


def test_remove_session_workspace_does_not_follow_escape_symlink(tmp_path):
    s = _settings(tmp_path / "cache")
    sessions = tmp_path / "cache" / "sessions"
    sessions.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (sessions / "conv-link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不允许创建目录符号链接")
    assert remove_session_workspace("conv-link", s) is False
    assert outside.is_dir()
