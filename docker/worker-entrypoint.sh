#!/usr/bin/env bash
set -e

# MALLOC_ARENA_MAX=2 significantly reduces memory fragmentation in glibc
# for long-running Python multi-threaded/asyncio processes.
export MALLOC_ARENA_MAX=2
export ENABLE_LITELLM="${ENABLE_LITELLM:-false}"
export DATA_DIR="${DATA_DIR:-/var/lib/pageindex/data}"
export LOG_DIR="${LOG_DIR:-/var/log/pageindex}"

mkdir -p "${DATA_DIR}" "${LOG_DIR}"

# Forward signals properly to the python process
exec uv run --no-sync python -m app.worker
