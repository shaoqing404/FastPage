# Phase IE-5 Routing Asset Backfill Runbook

本文档覆盖 routing asset 缺失扫描、样本验证、显式回填和回滚。目标是运维可见、可控、可回滚；工具默认只读，不会自动执行破坏性操作。

提交边界见 `docs/phase4_7/routing_infrastructure_integration_scope.md`，不要把已有 retrieval baseline 修复归入本批 IE 基建。

配套脚本：

```bash
uv run python scripts/phase47/routing_asset_maintenance.py --help
```

## 1. 前置检查

所有命令都会先检查：

- `alembic_version` 是否等于当前 Alembic head
- `documents`、`document_versions`、`document_routing_nodes` 是否存在
- routing asset 相关列是否齐全

如果本地 `data/app.db` 未迁移到 head 或缺表，工具会输出 `status=blocked` 和 rebuild 提示，不会继续扫描或回填。

先执行只读扫描：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/routing_asset_maintenance.py scan \
  --sample-limit 20 \
  --output results/routing_asset_scan_latest.json
```

报告会包含：

- 缺失 routing asset 的 document/version 范围
- failed routing asset 的 document/version 范围
- low-summary-coverage 样本
- 节点数、summary 覆盖率、失败率、缺失率
- execute 模式将修改的表与版本范围

## 2. 样本验证

`validate` 是只读别名，用于输出运维样本摘要：

```bash
uv run python scripts/phase47/routing_asset_maintenance.py validate \
  --summary-threshold 1.0 \
  --sample-limit 20
```

不要在未审阅 `quality_summary` 前执行 backfill。当前样本如果处于 summary 覆盖率混合态，应先记录 `low_summary_coverage` 范围。

## 2.1 Build Hook Flags

在线 parse 的 routing asset hook 使用以下 canonical env：

- `ROUTING_ROUTE_DOCS_BUILD_MODE`
- `ROUTING_SYNTHETIC_QUERIES_BUILD_MODE`
- `ROUTING_EMBEDDINGS_BUILD_MODE`

取值只按三档运维语义解释：

- `disabled`：默认值，不生成可选资产，不影响当前搜索主链路。
- `dry_run`：只写 build metadata / readiness，不落可选资产。
- `enabled`：仅允许显式启用；`route_docs` 可随 routing index 落盘，`synthetic_queries` 和 `embeddings` 仍只进入 pending backfill 语义，不接在线检索。

兼容旧脚本或手工配置时，代码还接受这些别名：`off/false/no` -> `disabled`，`dryrun/dry` -> `dry_run`，`on/true/persist/materialize/build` -> `enabled`。旧 singular env `ROUTING_ROUTE_DOC_BUILD_MODE` 只作为 `ROUTING_ROUTE_DOCS_BUILD_MODE` 的 fallback 读取；新配置必须使用 plural canonical name。

## 3. 显式回填

默认 dry-run：

```bash
uv run python scripts/phase47/routing_asset_maintenance.py backfill
```

真正回填必须显式 opt-in：

```bash
uv run python scripts/phase47/routing_asset_maintenance.py backfill \
  --execute \
  --rollback-manifest results/routing_asset_backfill_rollback_latest.json
```

执行模式只处理：

- `parse_status=index_ready`
- 有 `parsed_structure_path`
- 当前 routing asset 缺失或 failed 的版本

默认不会重写 low-summary-coverage 版本。需要把低覆盖版本也纳入重建时，必须额外加：

```bash
--include-low-summary
```

执行后脚本会生成 rollback manifest，记录每个被修改版本的原始 `document_versions` routing 字段和原始 `document_routing_nodes` 行。

## 4. 回滚

回滚默认也是 dry-run：

```bash
uv run python scripts/phase47/routing_asset_maintenance.py rollback \
  --manifest results/routing_asset_backfill_rollback_latest.json
```

真正回滚必须显式 opt-in：

```bash
uv run python scripts/phase47/routing_asset_maintenance.py rollback \
  --manifest results/routing_asset_backfill_rollback_latest.json \
  --execute
```

回滚恢复 DB 元数据和 `document_routing_nodes` 行。脚本不会自动删除已写入的 storage artifact；如需清理本地或 MinIO artifact，先审阅 manifest 中的版本范围，再按 `reset_runbook.md` 的 repo-owned 范围执行清理或重建。

## 5. Rebuild 路径

如果扫描输出 `status=blocked`：

```bash
uv run python scripts/phase47/runtime_reset.py rebuild
uv run python scripts/phase47/routing_asset_maintenance.py scan
```

如果需要清空运行面后重建，先按 `reset_runbook.md` dry-run 并显式执行对应 reset，再运行 `rebuild_and_bootstrap_runbook.md`。

## 6. 安全边界

- 不依赖外部向量库。
- 不调用在线 routing。
- 不挂入服务启动路径。
- 不默认重写现有文档。
- 不在 schema 未到 head 时继续执行。
