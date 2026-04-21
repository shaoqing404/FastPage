# Phase 4.7 Reset Runbook

本文档定义 `Phase 4.7` 的安全 reset 流程，目标是在不误删共享基础设施数据的前提下，把环境恢复到可重建状态。

## 1. 安全边界

只允许清理本项目拥有的数据：

- MySQL 中由本仓库迁移管理的表
- MinIO 中当前 `MINIO_BUCKET` 下、当前 `MINIO_PREFIX_PATH/tenants/` 前缀内的对象
- 本仓库下的本地运行目录：`data/`、`logs/`、`results/`

绝对不要清理：

- 同一 MySQL 实例里不在本项目清单内的表
- 其他项目共用的 MinIO bucket 或前缀
- 其他项目使用的 Redis DB / queue
- repo 之外的本地缓存、构建目录或用户文件

## 2. 本项目拥有的数据范围

MySQL repo-owned 表：

- `alembic_version`
- `api_keys`
- `audit_events`
- `chat_messages`
- `chat_runs`
- `chat_sessions`
- `chat_skill_documents`
- `chat_skills`
- `compliance_checks`
- `compliance_runs`
- `document_versions`
- `documents`
- `knowledge_base_documents`
- `knowledge_bases`
- `migration_review_items`
- `model_providers`
- `parse_jobs`
- `revoked_tokens`
- `tenant_memberships`
- `tenants`
- `users`
- `workspace_invites`
- `workspace_memberships`
- `workspaces`

本地运行目录：

- `data`
- `logs`
- `results`

MinIO repo-owned 根前缀：

- `MINIO_BUCKET`
- `MINIO_PREFIX_PATH/tenants/`

## 3. Reset 前检查

先确认 `.env` 正在指向你想操作的运行面：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/runtime_reset.py describe
```

继续之前应满足：

- API / worker 已停止，或环境已静止
- 输出中的 `database_url`、`storage_backend`、`minio_bucket`、`minio_root_prefix` 都符合预期
- 如果是共享 MySQL / MinIO，操作者已确认这些目标确实归本项目所有

## 4. 推荐 reset 顺序

1. 停止 API / worker
2. 清理 repo-owned MySQL 表
3. 清理 repo-owned MinIO 对象
4. 清理 repo-local 运行目录
5. 进入 rebuild / bootstrap 流程

## 5. MySQL Reset

先 dry-run 看目标：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/runtime_reset.py reset-mysql
```

真正执行：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/runtime_reset.py reset-mysql --execute
```

脚本行为：

- 只连接 `DATABASE_URL` 指向的 schema
- 只删除 repo-owned 表中的数据
- 发现未知表时直接停止，不做“顺手一起删”

## 6. MinIO Reset

先确认当前 MinIO scope：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/runtime_reset.py describe
```

真正执行前缀清理：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/runtime_reset.py reset-minio --execute
```

脚本只会删除当前 bucket 下、当前 repo root prefix 内的对象，不会扫描其他 bucket。

## 7. 本地运行目录 Reset

真正执行本地清理：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/runtime_reset.py reset-local --execute
```

只清理：

- `data/`
- `logs/`
- `results/`

不会清理：

- `examples/documents/*.pdf`
- `spec/`
- `.env`
- repo 外任何目录

## 8. 失败处理

如果任一步失败：

- 不要继续进入 rebuild 或 live validation
- 记录失败命令和 stderr
- 标明失败发生在 MySQL、MinIO、本地清理中的哪一段
- 若脚本提示存在未知表或未知对象范围，先人工确认归属，再决定后续动作

## 9. 下一步

reset 完成后，继续执行：

- [rebuild_and_bootstrap_runbook.md](rebuild_and_bootstrap_runbook.md)
- [verification_artifact_policy.md](verification_artifact_policy.md)
