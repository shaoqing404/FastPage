#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${SCRIPT_DIR}/.env.example" "${ENV_FILE}"
  echo "docker/.env was missing and has been created from docker/.env.example"
fi

set -a
source "${ENV_FILE}"
set +a

: "${WORKER_REPLICAS:=1}"

docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --build --scale worker="${WORKER_REPLICAS}"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" ps
