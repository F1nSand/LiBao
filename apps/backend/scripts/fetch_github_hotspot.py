"""定时抓取 GitHub trending → 写工作区 `github-hotspot/`（M8 热点垂直化）。

由 DevPanel / Windows 任务计划调度（项目无内置 scheduler，不引入 APScheduler）：
    uv run python scripts/fetch_github_hotspot.py --workspace-id <uuid> --since daily weekly monthly
    uv run python scripts/fetch_github_hotspot.py --root /path/to/workspace --since daily --language python
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 脚本位于 scripts/（非包），直接 `python scripts/xxx.py` 运行时需把项目根加入 sys.path（同 cleanup_test_orgs.py）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.services import github_hotspot as gh


def _resolve_root(args: argparse.Namespace) -> Path:
    if args.root:
        return Path(args.root).resolve()
    if args.workspace_id:
        return (Path(get_settings().workspaces_root) / args.workspace_id).resolve()
    raise SystemExit("必须提供 --workspace-id 或 --root 之一")


async def _main(args: argparse.Namespace) -> int:
    root = _resolve_root(args)
    if not root.is_dir():
        raise SystemExit(f"工作区目录不存在: {root}")
    failed = 0
    for since in args.since or ["daily"]:
        if not args.force and gh.is_trending_fresh(root, since):
            print(f"- {since}: 本地已新鲜（<24h），跳过（--force 强制）")
            continue
        print(f"抓取 {since} → {root}")
        try:
            repos = await asyncio.to_thread(gh.fetch_trending, since, args.language, args.spoken_language)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {since} 抓取失败（国内可能需代理）: {exc}")
            failed += 1
            continue
        if not repos:
            print(f"  ✗ {since} 空结果")
            failed += 1
            continue
        path = gh.persist_trending(root, since, gh.format_trending_md(repos, since, args.language))
        print(f"  ✓ {since}: {len(repos)} 个仓库 → {path}")
    return 1 if failed else 0


def main() -> int:
    p = argparse.ArgumentParser(description="定时抓取 GitHub trending 到工作区 github-hotspot/")
    p.add_argument("--workspace-id", help="工作区 UUID（root = workspaces_root/<id>）")
    p.add_argument("--root", help="直接指定工作区根目录路径")
    p.add_argument("--since", nargs="+", choices=["daily", "weekly", "monthly"], default=["daily"])
    p.add_argument("--language", help="可选：编程语言过滤，如 python")
    p.add_argument("--spoken-language", help="可选：口语代码，如 zh")
    p.add_argument("--force", action="store_true", help="忽略本地新鲜度，强制刷新")
    return asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
