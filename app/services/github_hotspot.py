"""GitHub 热点收集服务（M8 热点垂直化）。

trending（无官方 API）→ 复用 gtrending 库爬 github.com/trending；搜索/详情 → GitHub 官方 REST API。
落库到工作区本地 `github-hotspot/` 目录（trending 快照 + repo 概况 + index.json 新鲜度），对话优先搜本地。
所有失败降级为结构化 error（不抛），与 file_ops 降级风格一致。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings

_GITHUB_API = "https://api.github.com"
_TRENDING_MAX_AGE_HOURS = 24


def _headers() -> dict[str, str]:
    token = get_settings().github_token
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "agent-backend"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ---- GitHub 官方 REST API（搜索 / 详情）----


async def search_repos(query: str, limit: int = 10, language: str | None = None) -> dict[str, Any]:
    """GET /search/repositories → 项目列表（含 html_url 跳转链接）。"""
    q = f"{query} language:{language}" if language else query
    url = f"{_GITHUB_API}/search/repositories"
    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=15.0) as client:
            resp = await client.get(
                url, params={"q": q, "per_page": min(limit, 100), "sort": "stars", "order": "desc"}
            )
    except httpx.HTTPError as exc:
        return {"error": f"GitHub API 网络失败（国内可能需代理）: {str(exc)[:120]}"}
    if resp.status_code != 200:
        return {"error": _api_error(resp)}
    data = resp.json()
    items = [
        {
            "full_name": it["full_name"],
            "html_url": it["html_url"],
            "description": it.get("description") or "",
            "stargazers_count": it.get("stargazers_count", 0),
            "forks_count": it.get("forks_count", 0),
            "language": it.get("language") or "",
            "topics": it.get("topics") or [],
            "pushed_at": it.get("pushed_at") or "",
        }
        for it in data.get("items", [])
    ]
    result: dict[str, Any] = {"items": items, "total": data.get("total_count", 0)}
    if not get_settings().github_token:
        result["note"] = "未配置 GITHUB_TOKEN，匿名配额 60 req/h"
    return result


async def get_repo(owner: str, repo: str) -> dict[str, Any]:
    """GET /repos/{owner}/{repo} → 项目概况（含 html_url 跳转链接）。"""
    url = f"{_GITHUB_API}/repos/{owner}/{repo}"
    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=15.0) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        return {"error": f"GitHub API 网络失败（国内可能需代理）: {str(exc)[:120]}"}
    if resp.status_code != 200:
        return {"error": _api_error(resp)}
    it = resp.json()
    lic = it.get("license") or {}
    return {
        "full_name": it["full_name"],
        "html_url": it["html_url"],
        "description": it.get("description") or "",
        "stargazers_count": it.get("stargazers_count", 0),
        "forks_count": it.get("forks_count", 0),
        "open_issues_count": it.get("open_issues_count", 0),
        "subscribers_count": it.get("subscribers_count", 0),
        "language": it.get("language") or "",
        "topics": it.get("topics") or [],
        "license": lic.get("spdx_id") if lic else "",
        "homepage": it.get("homepage") or "",
        "pushed_at": it.get("pushed_at") or "",
    }


def _api_error(resp: httpx.Response) -> str:
    if resp.status_code in (401, 403):
        return f"GitHub API 鉴权/限流失败（{resp.status_code}）——token 失效或配额耗尽，可用本地缓存兜底"
    if resp.status_code == 404:
        return "GitHub API 404：仓库不存在或无权访问"
    return f"GitHub API 请求失败（{resp.status_code}）"


# ---- trending（gtrending 同步爬取）----


def fetch_trending(
    since: str = "daily", language: str | None = None, spoken_language: str | None = None
) -> list[dict[str, Any]]:
    """gtrending 同步抓取（阻塞网络请求，调用方需 asyncio.to_thread）。"""
    from gtrending import fetch_repos  # 惰性 import：测试可 monkeypatch 本函数绕过依赖

    repos = fetch_repos(language=language, spoken_language_code=spoken_language, since=since)
    return [
        {
            "fullname": r["fullname"],
            "url": r["url"],
            "description": r.get("description") or "",
            "language": r.get("language") or "",
            "stars": r.get("stars", 0),
            "forks": r.get("forks", 0),
            "current_period_stars": r.get("currentPeriodStars", 0),
        }
        for r in repos
    ]


# ---- markdown 格式化 ----

_LANG_LABEL = {"daily": "今日", "weekly": "本周", "monthly": "本月"}


def format_trending_md(repos: list[dict[str, Any]], since: str, language: str | None = None) -> str:
    fetched_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    scope = f"（{language}）" if language else ""
    lines = [
        f"# GitHub Trending {_LANG_LABEL.get(since, since)}{scope}",
        f"抓取时间：{fetched_at}",
        "",
        "| # | 仓库 | 语言 | Stars | Forks | 周期新增 | 简介 |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(repos, 1):
        desc = (r["description"] or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {i} | [{r['fullname']}]({r['url']}) | {r['language']} | {r['stars']} | {r['forks']} "
            f"| +{r['current_period_stars']} | {desc} |"
        )
    return "\n".join(lines)


def format_repo_md(repo: dict[str, Any]) -> str:
    topics = ", ".join(f"`{t}`" for t in (repo.get("topics") or [])) or "—"
    return "\n".join(
        [
            f"# [{repo['full_name']}]({repo['html_url']})",
            "",
            repo.get("description") or "（无描述）",
            "",
            "| 项 | 值 |",
            "|---|---|",
            f"| Stars | {repo.get('stargazers_count', 0)} |",
            f"| Forks | {repo.get('forks_count', 0)} |",
            f"| Issues | {repo.get('open_issues_count', 0)} |",
            f"| 语言 | {repo.get('language') or '—'} |",
            f"| Topics | {topics} |",
            f"| License | {repo.get('license') or '—'} |",
            f"| 主页 | {repo.get('homepage') or '—'} |",
            f"| 最近推送 | {repo.get('pushed_at') or '—'} |",
            "",
            f"跳转：{repo['html_url']}",
        ]
    )


# ---- 本地落库（工作区 github-hotspot/ 目录）----


def _hotspot_dir(root: str | Path) -> Path:
    return Path(root) / "github-hotspot"


def _read_index(root: str | Path) -> dict[str, Any]:
    p = _hotspot_dir(root) / "index.json"
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            pass
    return {}


def _write_index(root: str | Path, index: dict[str, Any]) -> None:
    p = _hotspot_dir(root) / "index.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def is_trending_fresh(root: str | Path, since: str, max_age_hours: int = _TRENDING_MAX_AGE_HOURS) -> bool:
    ts = _read_index(root).get("trending", {}).get(since)
    if not ts:
        return False
    try:
        last = datetime.fromisoformat(str(ts))
    except ValueError:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return (datetime.now(UTC) - last).total_seconds() < max_age_hours * 3600


def persist_trending(root: str | Path, since: str, markdown: str) -> str:
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    p = _hotspot_dir(root) / "trending" / f"{date_str}_{since}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(markdown, encoding="utf-8")
    index = _read_index(root)
    index.setdefault("trending", {})[since] = datetime.now(UTC).isoformat()
    _write_index(root, index)
    return str(p)


def read_trending_file(root: str | Path, since: str) -> str | None:
    """读最近的 {since} 快照（兜底用，不区分日期）。"""
    d = _hotspot_dir(root) / "trending"
    if not d.is_dir():
        return None
    files = sorted(d.glob(f"*_{since}.md"), reverse=True)
    if not files:
        return None
    try:
        return files[0].read_text(encoding="utf-8")
    except OSError:
        return None


def repo_cache_path(root: str | Path, owner: str, repo: str) -> Path:
    return _hotspot_dir(root) / "repos" / f"{owner}__{repo}.md"


def read_repo_file(root: str | Path, owner: str, repo: str) -> str | None:
    p = repo_cache_path(root, owner, repo)
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def persist_repo(root: str | Path, owner: str, repo: str, markdown: str) -> str:
    p = repo_cache_path(root, owner, repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(markdown, encoding="utf-8")
    return str(p)
