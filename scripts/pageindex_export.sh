#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPORT_DIR="${1:-${HOME}/Desktop/pageindex-export}"
COMPOSE_FILE="${ROOT_DIR}/docker/docker-compose.yml"
ENV_FILE="${ROOT_DIR}/docker/.env"
PROJECT_NAME="${PAGEINDEX_COMPOSE_PROJECT_NAME:-docker}"

if [ ! -f "${ENV_FILE}" ]; then
  echo "Missing ${ENV_FILE}. Configure docker/.env before exporting." >&2
  exit 1
fi

mkdir -p \
  "${EXPORT_DIR}/code" \
  "${EXPORT_DIR}/data/mysql" \
  "${EXPORT_DIR}/data/elasticsearch" \
  "${EXPORT_DIR}/data/minio" \
  "${EXPORT_DIR}/images" \
  "${EXPORT_DIR}/scripts" \
  "${EXPORT_DIR}/docs"

echo "Exporting code to ${EXPORT_DIR}/code/PageIndex-Service"
rsync -a --delete \
  --delete-excluded \
  --exclude ".git/" \
  --exclude ".venv/" \
  --exclude "node_modules/" \
  --exclude "frontend/node_modules/" \
  --exclude "data/" \
  --exclude "results/" \
  --exclude ".pytest_cache/" \
  --exclude "specs/" \
  --exclude ".tmp_*" \
  --exclude ".tmp_*/" \
  --exclude ".env" \
  --exclude ".env.*" \
  --exclude "docker/.env" \
  --exclude ".DS_Store" \
  "${ROOT_DIR}/" "${EXPORT_DIR}/code/PageIndex-Service/"

cp "${ROOT_DIR}/scripts/pageindex_import.sh" "${EXPORT_DIR}/scripts/pageindex_import.sh"
chmod +x "${EXPORT_DIR}/scripts/pageindex_import.sh"

echo "Saving Docker images"
images=(
  "pageindex-service-api:local"
  "pageindex-service-frontend:local"
  "mysql:8.4"
  "redis:7-alpine"
  "minio/minio:RELEASE.2025-02-28T09-55-16Z"
  "elasticsearch:8.19.15"
)
existing_images=()
for image in "${images[@]}"; do
  if docker image inspect "${image}" >/dev/null 2>&1; then
    existing_images+=("${image}")
  else
    echo "Skipping missing image: ${image}" >&2
  fi
done
if [ "${#existing_images[@]}" -gt 0 ]; then
  docker save -o "${EXPORT_DIR}/images/pageindex-images.tar" "${existing_images[@]}"
fi

echo "Exporting MySQL dump"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full exec -T mysql \
  sh -lc 'MYSQL_PWD="${MYSQL_PASSWORD}" mysqldump --no-tablespaces --single-transaction -u"${MYSQL_USER}" "${MYSQL_DATABASE}"' \
  > "${EXPORT_DIR}/data/mysql/pageindex_dump.sql"

echo "Exporting Elasticsearch metadata and best-effort documents"
curl -fsS "http://127.0.0.1:9200/_all/_settings" \
  > "${EXPORT_DIR}/data/elasticsearch/settings.json" || true
curl -fsS "http://127.0.0.1:9200/_all/_mapping" \
  > "${EXPORT_DIR}/data/elasticsearch/mapping.json" || true
curl -fsS -H "Content-Type: application/json" \
  -X POST "http://127.0.0.1:9200/_all/_search?size=10000" \
  -d '{"query":{"match_all":{}}}' \
  > "${EXPORT_DIR}/data/elasticsearch/es_full_export.json" || true

echo "Exporting MinIO bucket"
docker run --rm \
  --network "${PROJECT_NAME}_default" \
  --env-file "${ENV_FILE}" \
  -v "${EXPORT_DIR}/data/minio:/export" \
  --entrypoint /bin/sh \
  minio/mc:latest \
  -lc 'mc alias set pageindex http://minio:9000 "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" >/dev/null && mc mirror --overwrite "pageindex/${MINIO_BUCKET}" /export' \
  || echo "MinIO export skipped or incomplete; check bucket/service status." >&2

cat > "${EXPORT_DIR}/docs/DEPLOY-GUIDE.md" <<'GUIDE'
# PageIndex-Service Export Deploy Guide

This bundle intentionally does not include private `.env` files or API keys.
It is designed for local full-mode Docker deployment on a target server after
the target operator configures `code/PageIndex-Service/docker/.env`.

## Contents

- `code/PageIndex-Service`: repository snapshot without `.git`, virtualenvs, node modules, specs, or private env files
- `images/pageindex-images.tar`: Docker image archive when source images were present
- `images/pageindex-images-amd64.tar`: amd64 distribution image archive, when built
- `images/pageindex-images-arm64.tar`: arm64 distribution image archive, when built
- `data/mysql/pageindex_dump.sql`: MySQL dump
- `data/minio`: MinIO bucket mirror
- `data/elasticsearch`: Elasticsearch settings, mappings, and best-effort document export
- `scripts/pageindex_import.sh`: best-effort restore helper

## What Is And Is Not Restored

- MySQL: exported as SQL dump and can be restored by the helper.
- MinIO: exported as object files and can be restored by the helper.
- Elasticsearch: exported as settings, mappings, and a best-effort search snapshot. The helper does not replay ES automatically; rebuild ES indexes from application data when possible.
- Redis: not exported or restored. Redis is treated as queue/cache runtime state, not durable business data.
- Private env/API keys: not included. Configure them on the target server.

## Default Conflict Policy

The import helper defaults to target-data-first behavior:

```bash
PAGEINDEX_IMPORT_DATA_POLICY=keep-existing
```

With this default:

- If the target MySQL database already has tables, MySQL import is skipped.
- If the target MinIO bucket already has objects, MinIO import is skipped.
- The exported data is only restored into empty target components.

This is the recommended policy when the target server may already contain real data.

Other explicit policies:

```bash
# Start services and load images, but never restore MySQL/MinIO data.
PAGEINDEX_IMPORT_DATA_POLICY=skip-data bash scripts/pageindex_import.sh "$(pwd)" "$(pwd)/code/PageIndex-Service"

# Destructive: reset target MySQL database and replace MinIO bucket contents.
PAGEINDEX_IMPORT_DATA_POLICY=overwrite PAGEINDEX_IMPORT_CONFIRM=overwrite \
  bash scripts/pageindex_import.sh "$(pwd)" "$(pwd)/code/PageIndex-Service"
```

Use `overwrite` only for a fresh test host or after a manual backup.

## One-Command Restore

1. Copy or unpack this export directory on the target machine.
2. Configure `code/PageIndex-Service/docker/.env` from `docker/.env.example`.
3. Run:

```bash
bash scripts/pageindex_import.sh "$(pwd)" "$(pwd)/code/PageIndex-Service"
```

The helper loads local images, starts MySQL/Redis/MinIO/Elasticsearch, restores MySQL/MinIO only according to the data policy above, then starts API and frontend.

## Target Server Checklist For AI PM

1. Confirm Docker and Docker Compose are available.
2. Confirm whether the target already has PageIndex data.
3. Configure `code/PageIndex-Service/docker/.env`; do not paste real keys into code or docs.
4. Choose data policy:
   - Existing production data: keep default `keep-existing`.
   - Fresh machine and import desired: keep default; import proceeds if MySQL/MinIO are empty.
   - Code-only rollout: set `PAGEINDEX_IMPORT_DATA_POLICY=skip-data`.
   - Full replacement: set `PAGEINDEX_IMPORT_DATA_POLICY=overwrite PAGEINDEX_IMPORT_CONFIRM=overwrite` after backup.
5. Run the restore helper.
6. Verify:

```bash
curl -fsS http://127.0.0.1:22223/healthz
curl -fsS http://127.0.0.1:5173/providers
docker compose --env-file code/PageIndex-Service/docker/.env \
  -f code/PageIndex-Service/docker/docker-compose.yml --profile full ps
```

7. If ES-backed search results are missing, rebuild indexes through the application flow instead of replaying `data/elasticsearch` directly.

## Architecture

The default Docker path uses `docker/Dockerfile`, which supports `linux/amd64` and `linux/arm64`.
Set `API_DOCKERFILE=docker/Dockerfile.arm64` only when you explicitly want the ARM64-tuned file.

## Sensitive Terms

Before distributing outside the current environment, check whether the bundle should redact or exclude customer-specific terms such as operation manuals, airline names, customer names, tenant names, or route identifiers. The export helper excludes private env files, but it does not automatically redact business content stored in MySQL, MinIO, or documents.
GUIDE

cat > "${EXPORT_DIR}/README.txt" <<EOF
PageIndex-Service export generated at $(date -u +"%Y-%m-%dT%H:%M:%SZ")

Private env files and API keys are excluded.
MySQL and MinIO data are included. Redis is not included. Elasticsearch is included as best-effort metadata/search snapshots and is not automatically replayed.

Start here:
  ${EXPORT_DIR}/docs/DEPLOY-GUIDE.md

Restore helper:
  bash ${EXPORT_DIR}/scripts/pageindex_import.sh ${EXPORT_DIR} ${EXPORT_DIR}/code/PageIndex-Service

Default restore policy:
  PAGEINDEX_IMPORT_DATA_POLICY=keep-existing
  Target MySQL/MinIO data wins when conflicts are detected.
EOF

find "${EXPORT_DIR}" -name ".DS_Store" -delete

echo "Export complete: ${EXPORT_DIR}"
