"""GitHub 热点收集内置工具（M8 热点垂直化）：tl_github_trending / tl_github_search / tl_github_repo。

trending 走 gtrending 库（爬 github.com/trending，无官方 API）；搜索/详情走 GitHub 官方 REST API。
落库到工作区 `github-hotspot/`；无工作区上下文 → 只返回数据不写文件。

返回值约定：**成功返回 markdown 字符串**（executor `_summarize` 对 str 原样透传、对 dict 截断 500 字符，
故展示型结果必须返回 str 才能让 LLM 看全）；失败返回 `{"error": ...}` dict（结构化降级）。
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.services import github_hotspot as gh
from app.tools.context import get_tool_workspace_root

_SINCE_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}


async def tl_github_trending_handler(
    since: str = "daily", language: str | None = None, spoken_language: str | None = None, refresh: bool = False
) -> Any:
    root = get_tool_workspace_root()
    # ① 本地新鲜 → 直接读回（对话优先搜本地）
    if root and not refresh and gh.is_trending_fresh(root, since):
        md = gh.read_trending_file(root, since)
        if md is not None:
            return f"{md}\n\n> 来源：本地缓存（<24h 新鲜）"
    # ② 实时抓取（gtrending 爬 github.com/trending）
    try:
        repos = await asyncio.to_thread(gh.fetch_trending, since, language, spoken_language)
    except Exception as exc:  # noqa: BLE001  被墙/反爬 → ③ API 近似榜 → ④ 本地旧缓存
        approx = await gh.search_trending_approx(days=_SINCE_DAYS.get(since, 7), language=language)
        if "error" not in approx:
            md = (
                f"> 近似榜（非官方 trending：直连被墙，近 {approx['days']} 天新建 + star 排序）"
                f" · {len(approx['items'])} 个仓库\n\n"
            )
            md += gh.format_trending_md(approx["items"], since, language)
            if root:
                path = gh.persist_trending(root, since, md)
                return f"{md}\n\n> 已落库 {path}"
            return md
        if root:
            md = gh.read_trending_file(root, since)
            if md is not None:
                return f"{md}\n\n> 实时抓取失败，本地快照兜底: {str(exc)[:100]}"
        return {"error": f"trending 抓取失败（国内可能需代理）: {str(exc)[:120]}"}
    if not repos:
        return {"error": "trending 抓取返回空结果"}
    md = gh.format_trending_md(repos, since, language)
    note = f"> 实时抓取 · {len(repos)} 个仓库"
    if root:
        note += f" · 已落库 {gh.persist_trending(root, since, md)}"
    return f"{md}\n\n{note}"


async def tl_github_search_handler(query: str, limit: int = 10, language: str | None = None) -> Any:
    result = await gh.search_repos(query, limit, language)
    if "error" in result:
        return result
    md = gh.format_search_md(result["items"], query, result["total"])
    if result.get("note"):
        md += f"\n\n> {result['note']}"
    return md


async def tl_github_repo_handler(owner: str, repo: str, refresh: bool = False) -> Any:
    root = get_tool_workspace_root()
    # ① 本地缓存
    if root and not refresh:
        md = gh.read_repo_file(root, owner, repo)
        if md is not None:
            return f"{md}\n\n> 来源：本地缓存"
    # ② 实时拉取
    result = await gh.get_repo(owner, repo)
    if "error" in result:
        return result
    md = gh.format_repo_md(result)
    notes = [n for n in (result.get("note"),) if n]
    if root:
        notes.append(f"已落库 {gh.persist_repo(root, owner, repo, md)}")
    return f"{md}\n\n> " + " · ".join(notes) if notes else md
