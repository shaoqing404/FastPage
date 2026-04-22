#!/usr/bin/env bash
set -e

# MALLOC_ARENA_MAX=2 significantly reduces memory fragmentation in glibc
# for long-running Python multi-threaded/asyncio processes.
export MALLOC_ARENA_MAX=2

# Forward signals properly to the python process
exec python -m app.worker
