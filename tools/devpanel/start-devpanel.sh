#!/usr/bin/env bash
# Agent DevPanel launcher (single window): bash start-devpanel.sh
# Two services (backend/frontend) all in one screen.
# Stop: Ctrl+C (reclaims backend/frontend processes)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
exec uv run python main.py --port 9100 "$@"
