"""GitHub 热点收集服务（M8 热点垂直化）。

trending（无官方 API）→ 复用 gtrending 库爬 github.com/trending；搜索/详情 → GitHub 官方 REST API。
落库到工作区本地 `github-hotspot/` 目录（trending 快照 + repo 概况 + index.json 新鲜度），对话优先搜本地。
所有失败降级为结构化 error（不抛），与 file_ops 降级风格一致。
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
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


def _proxy() -> str | None:
    """httpx 显式代理（None = 走 trust_env，读系统 HTTP_PROXY/HTTPS_PROXY）。"""
    return get_settings().github_proxy


@contextmanager
def _proxy_env():
    """gtrending 的 requests 读 os.environ 代理 → 临时注入 HTTPS_PROXY/HTTP_PROXY，用完还原（不影响 LLM 出站）。"""
    proxy = get_settings().github_proxy
    if not proxy:
        yield
        return
    old = {k: os.environ.get(k) for k in ("HTTPS_PROXY", "HTTP_PROXY")}
    os.environ["HTTPS_PROXY"] = proxy
    os.environ["HTTP_PROXY"] = proxy
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _mirror() -> str:
    """GitHub 镜像前缀（直连失败时匿名兜底）。空串/None = 禁用镜像。"""
    m = (get_settings().github_mirror or "").strip().rstrip("/")
    return f"{m}/" if m else ""


def _anon_headers() -> dict[str, str]:
    """匿名 headers：镜像兜底不带 token（防泄漏给第三方）。"""
    return {"Accept": "application/vnd.github+json", "User-Agent": "agent-backend"}


async def _api_request(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET 官方 API（path 如 /search/repositories）：直连（带 token）→ 网络失败/5xx 经镜像（匿名）。

    返回 {'ok': bool, 'data'?, 'via_mirror'?, 'status'?, 'error'?}。
    """
    url = f"{_GITHUB_API}{path}"
    try:
        async with httpx.AsyncClient(headers=_headers(), timeout=15.0, proxy=_proxy()) as client:
            resp = await client.get(url, params=params)
        if resp.status_code == 200:
            return {"ok": True, "data": resp.json()}
        if resp.status_code in (401, 403, 404):
            return {"ok": False, "status": resp.status_code, "error": _api_error(resp)}
    except httpx.HTTPError:
        pass  # 直连网络失败 → 走镜像兜底
    mirror = _mirror()
    if mirror:
        try:
            async with httpx.AsyncClient(headers=_anon_headers(), timeout=15.0) as client:
                mresp = await client.get(mirror + url, params=params)
            if mresp.status_code == 200:
                return {"ok": True, "data": mresp.json(), "via_mirror": True}
            return {"ok": False, "status": mresp.status_code, "error": _api_error(mresp)}
        except httpx.HTTPError:
            pass
    return {"ok": False, "error": "GitHub API 网络失败（直连与镜像均不可达，国内可能需代理）"}


# ---- GitHub 官方 REST API（搜索 / 详情）----


async def search_repos(query: str, limit: int = 10, language: str | None = None) -> dict[str, Any]:
    """GET /search/repositories → 项目列表（含 html_url 跳转链接）。直连失败经镜像匿名兜底。"""
    q = f"{query} language:{language}" if language else query
    r = await _api_request(
        "/search/repositories", {"q": q, "per_page": min(limit, 100), "sort": "stars", "order": "desc"}
    )
    if not r["ok"]:
        return {"error": r["error"]}
    data = r["data"]
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
    if r.get("via_mirror"):
        result["note"] = "经镜像获取（匿名）"
    elif not get_settings().github_token:
        result["note"] = "未配置 GITHUB_TOKEN，匿名配额 60 req/h"
    return result


async def get_repo(owner: str, repo: str) -> dict[str, Any]:
    """GET /repos/{owner}/{repo} → 项目概况（含 html_url 跳转链接）。直连失败经镜像匿名兜底。"""
    r = await _api_request(f"/repos/{owner}/{repo}")
    if not r["ok"]:
        return {"error": r["error"]}
    it = r["data"]
    lic = it.get("license") or {}
    result: dict[str, Any] = {
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
    if r.get("via_mirror"):
        result["note"] = "经镜像获取（匿名）"
    return result


async def search_trending_approx(days: int = 7, limit: int = 25, language: str | None = None) -> dict[str, Any]:
    """trending 近似（官方 API，可经镜像）：近 N 天新建 + star 排序。非 GitHub 官方 trending 算法。"""
    from datetime import timedelta

    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
    q = f"created:>{since}" + (f" language:{language}" if language else "")
    r = await _api_request(
        "/search/repositories", {"q": q, "per_page": min(limit, 100), "sort": "stars", "order": "desc"}
    )
    if not r["ok"]:
        return {"error": r["error"]}
    items = [
        {
            "fullname": it["full_name"],
            "url": it["html_url"],
            "description": it.get("description") or "",
            "language": it.get("language") or "",
            "stars": it.get("stargazers_count", 0),
            "forks": it.get("forks_count", 0),
            "current_period_stars": 0,  # 搜索 API 无周期增量；近似榜用总 star 排序
        }
        for it in r["data"].get("items", [])
    ]
    return {"items": items, "approx": True, "days": days, "via_mirror": bool(r.get("via_mirror"))}


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

    with _proxy_env():
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


def format_search_md(items: list[dict[str, Any]], query: str, total: int) -> str:
    """搜索结果为 markdown 列表（LLM 可直接读用，含跳转链接）。"""
    lines = [f"## GitHub 搜索「{query}」（前 {len(items)} / 共 {total}）", ""]
    for i, it in enumerate(items, 1):
        lines.append(
            f"{i}. **[{it['full_name']}]({it['html_url']})** ⭐{it['stargazers_count']} · {it['language'] or '—'}"
        )
        if it.get("description"):
            lines.append(f"   {it['description']}")
    return "\n".join(lines)


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
