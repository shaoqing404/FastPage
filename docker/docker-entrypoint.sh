#!/usr/bin/env bash
set -euo pipefail

RUNTIME_MODE="full"
UVICORN_RELOAD="false"
API_PID=""
WORKER_PID=""

for arg in "$@"; do
    case "${arg}" in
        full|--full)
            RUNTIME_MODE="full"
            ;;
        local|--local|standalone|--standalone)
            RUNTIME_MODE="local"
            ;;
        reload|--reload)
            UVICORN_RELOAD="true"
            ;;
        *)
            echo "Unsupported argument: ${arg}. Use 'local' for API-only startup, or no flag for API + worker." >&2
            exit 1
            ;;
    esac
done

echo "==> Running database migrations..."
python -m alembic upgrade head

UVICORN_CMD=(python -m uvicorn app.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-22223}")
if [[ "${UVICORN_RELOAD}" == "true" ]]; then
    UVICORN_CMD+=(--reload)
fi

cleanup() {
    trap - EXIT INT TERM

    if [[ -n "${WORKER_PID}" ]] && kill -0 "${WORKER_PID}" 2>/dev/null; then
        kill "${WORKER_PID}" 2>/dev/null || true
    fi
    if [[ -n "${API_PID}" ]] && kill -0 "${API_PID}" 2>/dev/null; then
        kill "${API_PID}" 2>/dev/null || true
    fi

    if [[ -n "${WORKER_PID}" ]]; then
        wait "${WORKER_PID}" 2>/dev/null || true
    fi
    if [[ -n "${API_PID}" ]]; then
        wait "${API_PID}" 2>/dev/null || true
    fi
}

terminate() {
    cleanup
    exit 143
}

trap cleanup EXIT
trap terminate INT TERM

if [[ "${RUNTIME_MODE}" == "full" ]]; then
    echo "==> Mode: Full (MySQL/Redis)"
    echo "==> Starting Worker Node(s) in background (Count controlled by WORKER_PROCESS_COUNT)..."
    export MALLOC_ARENA_MAX=2
    python -m app.worker &
    WORKER_PID=$!
else
    echo "==> Mode: Local (SQLite/Local Queue)"
    echo "==> Local mode is API-only and is not recommended for production."
fi

if [[ "${UVICORN_RELOAD}" == "true" ]]; then
    echo "==> Starting API Service with hot-reload enabled..."
else
    echo "==> Starting API Service..."
fi
"${UVICORN_CMD[@]}" &
API_PID=$!

if [[ "${RUNTIME_MODE}" == "full" ]]; then
    while true; do
        if ! kill -0 "${WORKER_PID}" 2>/dev/null; then
            set +e
            wait "${WORKER_PID}"
            exit_code=$?
            set -e
            cleanup
            exit "${exit_code}"
        fi

        if ! kill -0 "${API_PID}" 2>/dev/null; then
            set +e
            wait "${API_PID}"
            exit_code=$?
            set -e
            cleanup
            exit "${exit_code}"
        fi

        sleep 1
    done
fi

set +e
wait "${API_PID}"
exit_code=$?
set -e
cleanup
exit "${exit_code}"
