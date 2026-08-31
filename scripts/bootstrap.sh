#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[1/3] syncing backend dependencies"
uv sync --project apps/backend
echo "[2/3] syncing DevPanel dependencies"
uv sync --project tools/devpanel
echo "[3/3] installing frontend dependencies"
npm ci --prefix apps/frontend
echo "Bootstrap complete."
