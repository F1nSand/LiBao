#!/usr/bin/env bash
set -eu

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
docker build -t libao-sandbox:py312-v1 -f "$ROOT/deploy/sandbox/Dockerfile" "$ROOT/deploy/sandbox"
