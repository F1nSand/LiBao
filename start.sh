#!/usr/bin/env bash
# ============================================================
# Agent 平台一键启动：db/redis → 迁移/种子 → 后端(:8000) → 前端(:5173)
# 用法：git-bash 下 `bash start.sh`（或 Windows 双击 start.cmd）
# 停止：Ctrl+C（会同时停掉后端与前端）
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND="$(dirname "$ROOT")/FrontEnd"
BE_PORT=8000
FE_PORT=5173
HEALTH="http://127.0.0.1:${BE_PORT}/api/v1/system/health"

BE_PID=""
FE_PID=""
cleanup() {
  [ -n "$BE_PID" ] && kill "$BE_PID" 2>/dev/null || true
  [ -n "$FE_PID" ] && kill "$FE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[*]\033[0m %s\n' "$*"; }

# 等待 HTTP URL 就绪（最多 N 秒）
wait_url() {
  local url="$1" name="$2" n="${3:-60}" i
  for i in $(seq 1 "$n"); do
    if curl -sf --max-time 2 "$url" >/dev/null 2>&1; then
      log "$name 就绪"
      return 0
    fi
    sleep 2
  done
  warn "$name 未在 $((n * 2))s 内就绪"
  return 1
}

# ---- 1. 基础设施 ----
log "基础设施 db+redis"
if docker info >/dev/null 2>&1; then
  docker compose -f "$ROOT/docker-compose.yml" up -d db redis >/dev/null 2>&1
  # 等待 db healthy（最多 60s）
  for i in $(seq 1 30); do
    st=$(docker inspect -f '{{.State.Health.Status}}' agent-db 2>/dev/null || echo "missing")
    [ "$st" = "healthy" ] && { log "db healthy"; break; }
    sleep 2
    [ "$i" -eq 30 ] && { warn "db 未 healthy（docker compose ps 查看）"; }
  done
else
  warn "Docker 未运行，跳过基础设施（若 db 已在别处运行可继续，后续迁移/种子会验证）"
fi

# ---- 2. 迁移 + 种子（幂等，可重复执行）----
log "迁移 + 种子（幂等）"
( cd "$ROOT" && uv run alembic upgrade head && uv run python -m app.seed )

# ---- 3. 后端 ----
if curl -sf --max-time 2 "$HEALTH" >/dev/null 2>&1; then
  warn "后端已在 :$BE_PORT 运行，跳过启动"
else
  log "启动后端 :$BE_PORT"
  ( cd "$ROOT" && exec uv run uvicorn app.api.main:app --host 127.0.0.1 --port "$BE_PORT" ) &
  BE_PID=$!
  wait_url "$HEALTH" "后端" 60 || { cleanup; exit 1; }
fi

# ---- 4. 前端 ----
if [ ! -d "$FRONTEND/node_modules" ]; then
  log "安装前端依赖（首次）"
  ( cd "$FRONTEND" && npm install )
fi
if curl -sf --max-time 2 "http://127.0.0.1:${FE_PORT}/" >/dev/null 2>&1; then
  warn "前端已在 :$FE_PORT 运行，跳过启动"
else
  log "启动前端 :$FE_PORT（VITE_USE_MOCK=false → 走真实后端）"
  ( cd "$FRONTEND" && VITE_USE_MOCK=false exec npm run dev ) &
  FE_PID=$!
  wait_url "http://127.0.0.1:${FE_PORT}/" "前端" 90 || { cleanup; exit 1; }
fi

echo
ok "全部就绪，按 Ctrl+C 停止所有服务"
echo "  前端  http://localhost:${FE_PORT}   （admin/admin123）"
echo "  后端  http://localhost:${BE_PORT}/api/v1/system/health"
echo "  文档  http://localhost:${BE_PORT}/docs"
wait
