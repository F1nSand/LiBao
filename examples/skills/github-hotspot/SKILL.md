---
name: github-hotspot
description: 当用户想了解 GitHub 热点/榜单（日周月榜）或查询某个开源项目时使用。先查本地缓存，缺失/过期才实时拉取。
---

# GitHub 热点收集

## 工作流

**用户问 GitHub 榜单 / 热点时**：
1. 先用 `glob` / `read_file` 查本地 `github-hotspot/trending/` 下当日文件（文件名 `{日期}_{daily|weekly|monthly}.md`），命中且新鲜（<24h）直接用。
2. 缺失 / 过期 → 调 `github_trending(since=...)` 拉取（自动落库）再展示。

**用户问某个具体项目时**：
1. 先查本地 `github-hotspot/repos/{owner}__{repo}.md`，命中直接用。
2. 无 → 调 `github_search(query=...)` 定位，再 `github_repo(owner, repo)` 拿概况（自动落库）再展示。

## 输出规范
- 用 markdown 表格 + 仓库名跳转链接 `[owner/repo](https://github.com/owner/repo)`。
- 榜单要说明抓取时间与来源（本地缓存 / 实时）。
- 工具失败（限流 / 网络）时，提示本地缓存截止时间，不要盲目重试。

> 安装：把本文件复制到工作区 `.agent/skills/github-hotspot/SKILL.md`（该工作区对话时自动发现）。
> 依赖工具：`github_trending` / `github_search` / `github_repo`（内置工具，需在 /tools 启用）。
