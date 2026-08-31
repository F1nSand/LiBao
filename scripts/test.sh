#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
(
  cd "$ROOT/apps/backend"
  uv run ruff check .
  uv run pytest tests/
)
(
  cd "$ROOT/apps/frontend"
  npm run lint:check
  npm run typecheck
  npm run build
  npm run test:unit
  npm run test:e2e
)
echo "All tests passed."
