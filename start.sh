#!/usr/bin/env bash
# ============================================================
# Agent 平台一键启动（本地单机化）：仅启动 FastAPI API（:8000）
# 用法：git-bash 下 `bash start.sh`（或双击 start.cmd）
# 停止：Ctrl+C
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BE_PORT=8000
HEALTH="http://127.0.0.1:${BE_PORT}/api/v1/system/health"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[*]\033[0m %s\n' "$*"; }

# ---- 1. 依赖（首次）----
if [ ! -d "$ROOT/.venv" ]; then
  log "安装依赖（首次）"
  ( cd "$ROOT" && uv sync )
fi

# ---- 2. 后端（首启自动种子，无 Docker/迁移）----
runtime_state="absent"
if curl -sf --max-time 2 "$HEALTH" >/dev/null 2>&1; then
  runtime_state="$(cd "$ROOT" && uv run python scripts/check_backend_runtime.py "$HEALTH" 2>/dev/null || true)"
fi
if [ "${1:-}" = "restart" ]; then
  if [ "$runtime_state" = "current" ]; then
    ok "后端已是当前项目最新实例，无需重启"
  else
    warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
    warn "后端状态=$runtime_state；请关闭已验证的 Agent Backend 窗口后再次运行 start.sh"
  fi
  exit 0
fi
if [ "$runtime_state" = "current" ]; then
  ok "后端已在 :$BE_PORT 运行（当前项目/源码匹配），跳过启动"
elif [ "$runtime_state" != "absent" ]; then
  warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
  warn "检测到后端状态=$runtime_state；不会静默复用，请运行 start.sh restart 并按提示处理"
  exit 1
else
  log "启动后端 :$BE_PORT（127.0.0.1，本地单机）"
  ( cd "$ROOT" && exec uv run uvicorn app.api.main:app --host 127.0.0.1 --port "$BE_PORT" )
fi

echo
ok "API 已启动：http://127.0.0.1:${BE_PORT}/docs   （Ctrl+C 停止）"
