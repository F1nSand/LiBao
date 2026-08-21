"""M8 热点收集：github_hotspot 服务 + 工具（格式化/落库/新鲜度/降级）。monkeypatch 隔离网络。"""
from __future__ import annotations

from app.services import github_hotspot as gh
from app.tools.builtin import github_hotspot as gh_tools
from app.tools.context import set_tool_workspace_root

FAKE_REPOS = [
    {
        "fullname": "owner/repo-a",
        "url": "https://github.com/owner/repo-a",
        "description": "desc | with pipe",
        "language": "Python",
        "stars": 1000,
        "forks": 100,
        "current_period_stars": 50,
    },
    {
        "fullname": "owner/repo-b",
        "url": "https://github.com/owner/repo-b",
        "description": "",
        "language": "Go",
        "stars": 500,
        "forks": 50,
        "current_period_stars": 20,
    },
]

FAKE_REPO = {
    "full_name": "o/r",
    "html_url": "https://github.com/o/r",
    "description": "d",
    "stargazers_count": 1,
    "forks_count": 2,
    "open_issues_count": 3,
    "subscribers_count": 4,
    "language": "Rust",
    "topics": ["a", "b"],
    "license": "MIT",
    "homepage": "https://x",
    "pushed_at": "2026-01-01",
}


def test_format_trending_md():
    md = gh.format_trending_md(FAKE_REPOS, "daily")
    assert "[owner/repo-a](https://github.com/owner/repo-a)" in md
    assert "| Python | 1000 | 100 | +50 |" in md
    assert "desc \\| with pipe" in md  # 管道符转义
    assert "GitHub Trending 今日" in md


def test_format_repo_md():
    md = gh.format_repo_md(FAKE_REPO)
    assert "[o/r](https://github.com/o/r)" in md
    assert "跳转：https://github.com/o/r" in md
    assert "`a`" in md and "MIT" in md


def test_persist_trending_and_freshness(tmp_path):
    p = gh.persist_trending(tmp_path, "daily", "# md")
    assert p.endswith("_daily.md")
    assert (tmp_path / "github-hotspot" / "trending").is_dir()
    assert gh.is_trending_fresh(tmp_path, "daily")
    assert not gh.is_trending_fresh(tmp_path, "weekly")  # 未抓过
    assert gh.read_trending_file(tmp_path, "daily") == "# md"


def test_read_trending_file_none(tmp_path):
    assert gh.read_trending_file(tmp_path, "daily") is None


def test_repo_cache(tmp_path):
    p = gh.persist_repo(tmp_path, "o", "r", "# repo")
    assert p.endswith("o__r.md")
    assert gh.read_repo_file(tmp_path, "o", "r") == "# repo"
    assert gh.read_repo_file(tmp_path, "o", "nope") is None


async def test_trending_handler_persist(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "fetch_trending", lambda *a, **k: FAKE_REPOS)
    set_tool_workspace_root(str(tmp_path))
    try:
        out = await gh_tools.tl_github_trending_handler("daily")
    finally:
        set_tool_workspace_root(None)
    assert out["from_cache"] is False
    assert out["count"] == 2
    assert "repo-a" in out["markdown"]
    assert gh.read_trending_file(tmp_path, "daily") is not None


async def test_trending_handler_cache(tmp_path, monkeypatch):
    gh.persist_trending(tmp_path, "daily", "# cached")
    called = {"n": 0}
    monkeypatch.setattr(
        gh, "fetch_trending", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or FAKE_REPOS
    )
    set_tool_workspace_root(str(tmp_path))
    try:
        out = await gh_tools.tl_github_trending_handler("daily")
    finally:
        set_tool_workspace_root(None)
    assert out["from_cache"] is True
    assert called["n"] == 0  # 未触发实时抓取


async def test_trending_handler_fallback(tmp_path, monkeypatch):
    gh.persist_trending(tmp_path, "daily", "# old snapshot")

    def _boom(*a, **k):
        raise RuntimeError("blocked")

    monkeypatch.setattr(gh, "fetch_trending", _boom)
    set_tool_workspace_root(str(tmp_path))
    try:
        out = await gh_tools.tl_github_trending_handler("daily", refresh=True)
    finally:
        set_tool_workspace_root(None)
    assert out["from_cache"] is True
    assert "old snapshot" in out["markdown"]
    assert "兜底" in out["note"]


async def test_trending_handler_error_no_cache(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("blocked")

    monkeypatch.setattr(gh, "fetch_trending", _boom)
    set_tool_workspace_root(str(tmp_path))
    try:
        out = await gh_tools.tl_github_trending_handler("daily", refresh=True)
    finally:
        set_tool_workspace_root(None)
    assert "error" in out


async def test_search_handler_degrade(monkeypatch):
    async def _fake_search(*a, **k):
        return {"error": "限流"}

    monkeypatch.setattr(gh, "search_repos", _fake_search)
    out = await gh_tools.tl_github_search_handler("llm")
    assert out["error"] == "限流"


async def test_repo_handler_persist(tmp_path, monkeypatch):
    async def _fake_get_repo(*a, **k):
        return FAKE_REPO

    monkeypatch.setattr(gh, "get_repo", _fake_get_repo)
    set_tool_workspace_root(str(tmp_path))
    try:
        out = await gh_tools.tl_github_repo_handler("o", "r")
    finally:
        set_tool_workspace_root(None)
    assert out["from_cache"] is False
    assert "o/r" in out["markdown"]
    assert gh.read_repo_file(tmp_path, "o", "r") is not None
