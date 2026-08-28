#!/usr/bin/env sh
set -eu

docker build -t libao-sandbox:py312-v1 -f docker/sandbox/Dockerfile docker/sandbox
