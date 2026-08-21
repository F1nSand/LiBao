"""GitHub 热点收集内置工具（M8 热点垂直化）：tl_github_trending / tl_github_search / tl_github_repo。

trending 走 gtrending 库（爬 github.com/trending，无官方 API）；搜索/详情走 GitHub 官方 REST API。
落库到工作区 `github-hotspot/`；无工作区上下文 → 只返回数据不写文件。失败降级结构化 error（不抛）。
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.services import github_hotspot as gh
from app.tools.context import get_tool_workspace_root


async def tl_github_trending_handler(
    since: str = "daily", language: str | None = None, spoken_language: str | None = None, refresh: bool = False
) -> dict[str, Any]:
    root = get_tool_workspace_root()
    # ① 本地新鲜 → 直接读回（对话优先搜本地）
    if root and not refresh and gh.is_trending_fresh(root, since):
        md = gh.read_trending_file(root, since)
        if md is not None:
            return {"since": since, "from_cache": True, "markdown": md}
    # ② 实时抓取
    try:
        repos = await asyncio.to_thread(gh.fetch_trending, since, language, spoken_language)
    except Exception as exc:  # noqa: BLE001  反爬/网络失败 → 本地兜底
        if root:
            md = gh.read_trending_file(root, since)
            if md is not None:
                return {
                    "since": since,
                    "from_cache": True,
                    "markdown": md,
                    "note": f"实时抓取失败，用本地快照兜底: {str(exc)[:100]}",
                }
        return {"error": f"trending 抓取失败（国内可能需代理）: {str(exc)[:120]}"}
    if not repos:
        return {"error": "trending 抓取返回空结果"}
    md = gh.format_trending_md(repos, since, language)
    payload: dict[str, Any] = {"since": since, "count": len(repos), "from_cache": False, "markdown": md}
    if root:
        payload["path"] = gh.persist_trending(root, since, md)
    return payload


async def tl_github_search_handler(query: str, limit: int = 10, language: str | None = None) -> dict[str, Any]:
    return await gh.search_repos(query, limit, language)


async def tl_github_repo_handler(owner: str, repo: str, refresh: bool = False) -> dict[str, Any]:
    root = get_tool_workspace_root()
    # ① 本地缓存
    if root and not refresh:
        md = gh.read_repo_file(root, owner, repo)
        if md is not None:
            return {"owner": owner, "repo": repo, "from_cache": True, "markdown": md}
    # ② 实时拉取
    result = await gh.get_repo(owner, repo)
    if "error" in result:
        return result
    md = gh.format_repo_md(result)
    payload: dict[str, Any] = {**result, "from_cache": False, "markdown": md}
    if root:
        payload["path"] = gh.persist_repo(root, owner, repo, md)
    return payload
