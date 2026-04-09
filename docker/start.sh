#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
PROFILE="${PAGEINDEX_COMPOSE_PROFILE:-full}"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${SCRIPT_DIR}/.env.example" "${ENV_FILE}"
  echo "docker/.env was missing and has been created from docker/.env.example"
fi

set -a
source "${ENV_FILE}"
set +a

: "${WORKER_REPLICAS:=1}"

case "${PROFILE}" in
  full)
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full up -d --build --scale worker="${WORKER_REPLICAS}"
    ;;
  local)
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile local up -d --build
    ;;
  *)
    echo "Unsupported PAGEINDEX_COMPOSE_PROFILE=${PROFILE}. Use 'full' or 'local'." >&2
    exit 1
    ;;
esac

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps
