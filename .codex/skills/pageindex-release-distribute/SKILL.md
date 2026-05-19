---
name: pageindex-release-distribute
description: Use when releasing PageIndex-Service from a local workspace: inspect changes, commit and push eligible code, rebuild Docker images, refresh the desktop export bundle, and optionally distribute the exported code to an intranet host.
---

# PageIndex 发布与分发

当 PageIndex-Service 的任务同时涉及 git 提交/推送、Docker 重建、桌面导出、可选内网分发时，使用这个项目级 skill。

## 必问问题

开始前必须问用户两个短问题，除非当前请求已经明确回答：

1. 是否需要把刷新后的导出推送到某个内网地址？如果需要，确认 host、账号、目标路径，以及分发范围（`仅代码` 或 `完整导出包`）。
2. 是否需要屏蔽或排除客户限定词，例如运行手册、航司名称、客户名称、航线、租户名或其他敏感标识？如果需要，要求用户给出明确词表或模式。

不要打印密码、API key、token 或完整私有 `.env` 内容。如果传输需要凭据，只在命令/session 中使用用户提供的凭据。

## 默认边界

- 仓库根目录：`/Users/mac/Developer/element_workspace/PageIndex-Service`。
- Docker 默认使用 `full` 模式，不使用 local SQLite 模式。
- local/SQLite 模式视为即将废弃，只在相关时提醒。
- 永远不要提交或导出私有 env 文件：`.env`、`.env.*`、`docker/.env`。
- 除非用户明确覆盖边界，不要提交 `specs/` 或 `spec/` 工程过程文件。
- 不要假设客户内网 endpoint 可达，除非用户明确要求测试某个传输目标。
- 保留用户或其他 agent 的改动，不要回滚无关文件。

## 流程

1. 检查状态：

```bash
git status --short
git fetch origin main
git log --oneline --decorate --graph --left-right --cherry-pick origin/main...HEAD
```

查看 `git diff --stat`，识别可提交文件。排除私有 env 文件和过程产物。

2. 提交并推送：

- 只 stage 合规文件。
- 使用简洁的发布类 commit message。
- 如果本地和远端历史分叉，用 merge 或 rebase 合并 `origin/main`，不要丢任何一侧历史。
- 推送当前分支到 `origin`。

3. 重建本地 Docker full 栈：

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml --profile full build api frontend
docker compose --env-file docker/.env -f docker/docker-compose.yml --profile full up -d mysql redis minio elasticsearch api frontend
```

4. 验证服务健康：

```bash
curl -fsS http://127.0.0.1:22223/healthz
curl -fsS http://127.0.0.1:5173/providers
```

如果 Phase 5 runtime 路径有变更，优先跑容器内 targeted 测试：

```bash
docker compose --env-file docker/.env -f docker/docker-compose.yml --profile full exec -T api sh -c 'DATA_DIR=/tmp/pageindex-test-data uv run --with pytest python -m pytest tests/phase4/test_pageindex_llm_failfast.py tests/phase4/test_direct_chat_adapter.py tests/phase5/test_endpoint_resolution.py tests/phase4/test_pageindex_retrieval_contract.py tests/phase4/test_skill_stream_runtime_contract.py tests/phase4/test_provider_execution_model_normalization.py tests/phase4/test_node_embedding_service.py tests/phase4/test_pageindex_native_rerank.py -q'
```

5. 构建分发镜像包：

```bash
bash /Users/mac/.codex/skills/pageindex-docker-build/scripts/build_pageindex_images.sh \
  /Users/mac/Developer/element_workspace/PageIndex-Service \
  /Users/mac/Desktop/pageindex-export/images
```

6. 刷新桌面导出：

```bash
bash scripts/pageindex_export.sh /Users/mac/Desktop/pageindex-export
```

如果存在旧命名镜像 tar，清理掉，避免分发时拿错。然后确认导出包不包含私有文件和过程产物：

```bash
find /Users/mac/Desktop/pageindex-export/code/PageIndex-Service \
  \( -name .env -o -path '*/docker/.env' -o -path '*/.git/*' -o -path '*/node_modules/*' -o -path '*/specs/*' -o -name .DS_Store -o -name '.tmp_*' \) -print
```

7. 可选内网分发：

- 只有用户明确要求，或对必问问题回答“需要”时才执行。
- 仅代码分发优先使用 `rsync -az --delete`。
- 完整导出包分发前，先确认磁盘和网络预算足够。
- 告知目标服务器 AI PM：导入默认是 `PAGEINDEX_IMPORT_DATA_POLICY=keep-existing`，目标已有 MySQL/MinIO 数据优先，Redis 不导入，ES 快照不自动 replay。
- 传输后验证远端目标路径。

示例：

```bash
rsync -az --delete -e "ssh -o StrictHostKeyChecking=accept-new" \
  /Users/mac/Desktop/pageindex-export/code/PageIndex-Service/ \
  user@host:/target/PageIndex-Service/
```

## 汇报要求

最终报告说明：

- commit hash 和推送分支
- Docker 构建和启动结果
- 健康检查/测试结果
- 桌面导出路径和大小
- 镜像 tar 包名称
- 如执行了内网分发，说明目标地址和验证结果
- 客户词屏蔽/脱敏决策
- 剩余风险，包括是否未做客户内网实机 smoke
