#!/usr/bin/env bash
# Agent 开发面板启动（单窗口）：bash start-devpanel.sh，浏览器自动打开面板
# 四个服务（db/redis/backend/frontend）都在这一个界面里启停
# 停止：Ctrl+C（同时回收后端/前端进程，容器保持运行）
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec uv run python -m devpanel.main --port 9100 "$@"
