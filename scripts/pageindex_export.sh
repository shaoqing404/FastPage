#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXPORT_DIR="${1:-${HOME}/Desktop/pageindex-export}"
COMPOSE_FILE="${ROOT_DIR}/docker/docker-compose.yml"
ENV_FILE="${ROOT_DIR}/docker/.env"
PROJECT_NAME="${PAGEINDEX_COMPOSE_PROJECT_NAME:-docker}"

if [ ! -f "${ENV_FILE}" ]; then
  echo "缺少 ${ENV_FILE}。导出前请先配置 docker/.env。" >&2
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

echo "正在导出代码到 ${EXPORT_DIR}/code/PageIndex-Service"
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

echo "正在保存 Docker 镜像"
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
    echo "跳过不存在的镜像：${image}" >&2
  fi
done
if [ "${#existing_images[@]}" -gt 0 ]; then
  docker save -o "${EXPORT_DIR}/images/pageindex-images.tar" "${existing_images[@]}"
fi

echo "正在导出 MySQL 数据"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile full exec -T mysql \
  sh -lc 'MYSQL_PWD="${MYSQL_PASSWORD}" mysqldump --no-tablespaces --single-transaction -u"${MYSQL_USER}" "${MYSQL_DATABASE}"' \
  > "${EXPORT_DIR}/data/mysql/pageindex_dump.sql"

echo "正在导出 Elasticsearch 元数据和尽力而为的文档快照"
curl -fsS "http://127.0.0.1:9200/_all/_settings" \
  > "${EXPORT_DIR}/data/elasticsearch/settings.json" || true
curl -fsS "http://127.0.0.1:9200/_all/_mapping" \
  > "${EXPORT_DIR}/data/elasticsearch/mapping.json" || true
curl -fsS -H "Content-Type: application/json" \
  -X POST "http://127.0.0.1:9200/_all/_search?size=10000" \
  -d '{"query":{"match_all":{}}}' \
  > "${EXPORT_DIR}/data/elasticsearch/es_full_export.json" || true

echo "正在导出 MinIO bucket"
docker run --rm \
  --network "${PROJECT_NAME}_default" \
  --env-file "${ENV_FILE}" \
  -v "${EXPORT_DIR}/data/minio:/export" \
  --entrypoint /bin/sh \
  minio/mc:latest \
  -lc 'mc alias set pageindex http://minio:9000 "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" >/dev/null && mc mirror --overwrite "pageindex/${MINIO_BUCKET}" /export' \
  || echo "MinIO 导出被跳过或不完整；请检查 bucket 或服务状态。" >&2

cat > "${EXPORT_DIR}/docs/DEPLOY-GUIDE.md" <<'GUIDE'
# PageIndex-Service 导出部署指南

这个导出包不会包含私有 `.env` 文件或 API key。
它用于目标服务器上的本地 full 模式 Docker 部署。目标服务器操作人需要先配置
`code/PageIndex-Service/docker/.env`。

## 目录内容

- `code/PageIndex-Service`：代码快照，不包含 `.git`、虚拟环境、node modules、specs 或私有 env 文件。
- `images/pageindex-images.tar`：本地运行所需 Docker 镜像归档。
- `images/pageindex-images-amd64.tar`：amd64 架构分发镜像包，如果已构建。
- `images/pageindex-images-arm64.tar`：arm64 架构分发镜像包，如果已构建。
- `data/mysql/pageindex_dump.sql`：MySQL 数据库 dump。
- `data/minio`：MinIO bucket 镜像数据。
- `data/elasticsearch`：Elasticsearch settings、mapping 和尽力而为的文档查询快照。
- `scripts/pageindex_import.sh`：目标服务器导入/拉起辅助脚本。

## 哪些数据会恢复，哪些不会

- MySQL：已导出为 SQL dump，可由导入脚本恢复。
- MinIO：已导出为对象文件，可由导入脚本恢复。
- Elasticsearch：只导出 settings、mapping 和尽力而为的查询快照。导入脚本不会自动 replay ES，建议通过应用流程重建索引。
- Redis：不导出、不恢复。Redis 被视为队列/缓存运行态，不作为持久业务数据迁移。
- 私有 env/API key：不包含。请在目标服务器自行配置。

## 默认冲突策略

导入脚本默认采用“目标已有数据优先”策略：

```bash
PAGEINDEX_IMPORT_DATA_POLICY=keep-existing
```

默认策略下：

- 如果目标 MySQL 数据库已经有表，跳过 MySQL 导入。
- 如果目标 MinIO bucket 已经有对象，跳过 MinIO 导入。
- 只有目标组件为空时，才恢复导出包里的数据。

当目标服务器可能已有真实数据时，推荐保留这个默认策略。

其他显式策略：

```bash
# 只加载镜像和启动服务，不恢复 MySQL/MinIO 数据。
PAGEINDEX_IMPORT_DATA_POLICY=skip-data bash scripts/pageindex_import.sh "$(pwd)" "$(pwd)/code/PageIndex-Service"

# 破坏性操作：重置目标 MySQL，并替换 MinIO bucket 内容。
PAGEINDEX_IMPORT_DATA_POLICY=overwrite PAGEINDEX_IMPORT_CONFIRM=overwrite \
  bash scripts/pageindex_import.sh "$(pwd)" "$(pwd)/code/PageIndex-Service"
```

只有在全新测试机，或已完成手动备份后，才使用 `overwrite`。

## 一键恢复

1. 将本导出目录复制或解压到目标服务器。
2. 基于 `code/PageIndex-Service/docker/.env.example` 配置 `code/PageIndex-Service/docker/.env`。
3. 在导出目录根路径执行：

```bash
bash scripts/pageindex_import.sh "$(pwd)" "$(pwd)/code/PageIndex-Service"
```

脚本会加载本地镜像，启动 MySQL/Redis/MinIO/Elasticsearch，并按上面的数据策略恢复 MySQL/MinIO，最后启动 API 和前端。

## 目标服务器 AI PM 检查清单

1. 确认目标服务器已安装 Docker 和 Docker Compose。
2. 确认目标服务器是否已有 PageIndex 数据。
3. 配置 `code/PageIndex-Service/docker/.env`；不要把真实 key 写进代码或文档。
4. 选择数据策略：
   - 已有生产数据：保留默认 `keep-existing`。
   - 全新机器且需要导入数据：保留默认；MySQL/MinIO 为空时会自动导入。
   - 只更新代码和服务：设置 `PAGEINDEX_IMPORT_DATA_POLICY=skip-data`。
   - 完全替换：备份后设置 `PAGEINDEX_IMPORT_DATA_POLICY=overwrite PAGEINDEX_IMPORT_CONFIRM=overwrite`。
5. 运行导入脚本。
6. 验证：

```bash
curl -fsS http://127.0.0.1:22223/healthz
curl -fsS http://127.0.0.1:5173/providers
docker compose --env-file code/PageIndex-Service/docker/.env \
  -f code/PageIndex-Service/docker/docker-compose.yml --profile full ps
```

7. 如果 ES 检索结果缺失，优先通过应用流程重建索引，不要直接 replay `data/elasticsearch`。

## 架构说明

默认 Docker 路径使用 `docker/Dockerfile`，支持 `linux/amd64` 和 `linux/arm64`。
只有明确需要 ARM64 专用 Dockerfile 时，才设置 `API_DOCKERFILE=docker/Dockerfile.arm64`。

## 敏感词和客户信息

向当前环境之外分发前，请确认是否需要屏蔽客户限定词，例如运行手册、航司名称、客户名称、租户名称、航线标识等。
导出脚本会排除私有 env 文件，但不会自动清洗 MySQL、MinIO 或文档里的业务内容。
GUIDE

cat > "${EXPORT_DIR}/README.txt" <<EOF
PageIndex-Service 导出包生成时间：$(date -u +"%Y-%m-%dT%H:%M:%SZ")

本导出包不包含私有 env 文件或 API key。
本导出包包含 MySQL 和 MinIO 数据。
Redis 不包含在导出中。
Elasticsearch 只包含尽力而为的元数据/查询快照，不会自动 replay。

先看这里：
  ${EXPORT_DIR}/docs/DEPLOY-GUIDE.md

恢复脚本：
  bash ${EXPORT_DIR}/scripts/pageindex_import.sh ${EXPORT_DIR} ${EXPORT_DIR}/code/PageIndex-Service

默认恢复策略：
  PAGEINDEX_IMPORT_DATA_POLICY=keep-existing
  发生冲突时，以目标服务器已有 MySQL/MinIO 数据为准。
EOF

find "${EXPORT_DIR}" -name ".DS_Store" -delete

echo "导出完成：${EXPORT_DIR}"
