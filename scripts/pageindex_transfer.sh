#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  cat >&2 <<'EOF'
用法：
  scripts/pageindex_transfer.sh /path/to/pageindex-export user@host:/target/pageindex-export

说明：
  - 这是通用内网分发脚本，不绑定任何固定 IP。
  - 默认传输完整导出包：code、images、data、scripts、docs。
  - 私有 docker/.env 不在导出包内，目标机需要自行配置。
EOF
  exit 1
fi

EXPORT_DIR="${1%/}"
DEST="${2%/}"

if [ ! -d "${EXPORT_DIR}" ]; then
  echo "导出目录不存在：${EXPORT_DIR}" >&2
  exit 1
fi

for required in \
  "${EXPORT_DIR}/code/PageIndex-Service" \
  "${EXPORT_DIR}/scripts/pageindex_import.sh" \
  "${EXPORT_DIR}/docs/MIGRATION-RUNBOOK.md"; do
  if [ ! -e "${required}" ]; then
    echo "导出包缺少必要内容：${required}" >&2
    exit 1
  fi
done

if [ ! -f "${EXPORT_DIR}/images/pageindex-images-amd64.tar" ] && [ ! -f "${EXPORT_DIR}/images/pageindex-images-arm64.tar" ] && [ ! -f "${EXPORT_DIR}/images/pageindex-images.tar" ]; then
  echo "警告：导出包中没有 Docker 镜像 tar。目标内网机器可能会触发构建或启动失败。" >&2
fi

echo "正在分发完整导出包：${EXPORT_DIR} -> ${DEST}"
rsync -az --delete --info=progress2 \
  -e "ssh -o StrictHostKeyChecking=accept-new" \
  "${EXPORT_DIR}/" "${DEST}/"

cat <<EOF
分发完成。

目标服务器下一步：
  cd ${DEST#*:}
  cp -n code/PageIndex-Service/docker/.env.example code/PageIndex-Service/docker/.env
  # 编辑 code/PageIndex-Service/docker/.env
  bash scripts/pageindex_import.sh "\$(pwd)" "\$(pwd)/code/PageIndex-Service"

注意：
  - 不要直接在目标机执行 docker compose up -d api frontend。
  - 导入脚本会 docker load 离线镜像，并使用 --no-build 启动。
EOF
