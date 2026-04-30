# Routing Infrastructure Merge Boundary

本文档是当前脏 worktree 的合并/提交边界清单，只用于拆分 retrieval baseline 与本批 IE 基建增强。不要把本文档当作功能上线声明。

## 当前状态依据

- 已检查 `git status --short`，当前 worktree 同时包含 tracked 修改和 untracked 文件。
- 已检查 `git diff --name-only`，该命令只覆盖 tracked diff，不包含 untracked IE 文件和本地结果文件。
- 已检查以下关键 diff：`app/services/chat_service.py`、`app/services/compliance_service.py`、`app/services/pageindex_service.py`、`pageindex/utils.py`、`tests/phase4/test_pageindex_retrieval_contract.py`。
- 已检查 `docs/phase4_7/routing_infrastructure_integration_scope.md`。
- 已检查 IE 新文件：`app/models/routing_asset_contract.py`、`app/services/telemetry_service.py`、`scripts/phase47/routing_asset_maintenance.py`、`docs/phase4_7/routing_asset_backfill_runbook.md`。

## IE 基建文件清单

这些文件可归入 IE 基建提交，但提交说明必须保持为 contract、telemetry、schema、dry-run/backfill tooling，不得描述为在线 routing/embedding 已上线。

- `app/core/config.py`：`SYSTEM_EMBEDDING_*` dark contract，以及 `ROUTING_*_BUILD_MODE` 配置读取。
- `.env.example`、`docker/.env.example`：上述配置示例。
- `app/schemas/providers.py`、`app/services/provider_service.py`、`tests/phase4/test_provider_execution_model_normalization.py`：provider capability 中的 embedding model detection 与 embedding resolver dark contract。
- `app/services/telemetry_service.py`、`tests/phase4/test_ie4_telemetry_contract.py`：IE telemetry schema、embedding provider telemetry、routing asset coverage/missing/failure telemetry。
- `app/models/routing_asset_contract.py`、`tests/phase4/test_routing_asset_contract.py`：routing asset v1 schema/readiness normalization 与 legacy payload compatibility。
- `app/models/document.py`、`app/models/document_routing_node.py`、`app/models/__init__.py`：`DocumentVersion` routing asset metadata 与 `document_routing_nodes` model。
- `migrations/versions/20260423_0013_phase410_routing_index_schema.py`、`tests/phase4/test_migrations_smoke.py`、`tests/phase4/test_bootstrap_init_db.py`：routing index schema foundation 和迁移覆盖。
- `app/services/storage_service.py`：`routing_index.json` read/write normalization；其中 `ensure_run_reuse_cache()` 相关 hunks 属于 retrieval/runtime baseline，见后文人工 review。
- `app/services/parse_service.py`、`tests/phase4/test_parse_routing_index_pipeline.py`：parse/build pipeline 的 routing index payload、routing node rows、build telemetry、hook stub，默认 disabled 或 dry-run 语义。
- `app/services/runtime_observation_service.py`、`app/api/routers/runtime_observations.py`：只读 routing asset debug snapshot 与 runtime observation telemetry。
- `scripts/phase47/routing_asset_maintenance.py`、`tests/phase4/test_routing_asset_maintenance_tool.py`：scan/validate/backfill/rollback 工具；不得在本边界任务中运行 backfill/rollback。
- `docs/phase4_7/routing_infrastructure_integration_scope.md`、`docs/phase4_7/routing_asset_backfill_runbook.md`、`docs/phase4_7/routing_infrastructure_merge_boundary.md`：IE 边界、runbook 和本拆分清单。
- `README.md`、`docs/phase4_7/README.md`、`docs/phase4_7/closeout_checklist.md`、`docs/phase4_7/runtime_validation_checklist.md`：如内容只描述 IE contract、dry-run、验证边界，可随 IE 文档提交；若混入 retrieval baseline 验收结论，应拆出。

## Retrieval Baseline 文件清单

这些差异属于既有 retrieval contract / Phase 4.10 baseline 修复，应先独立合并为 baseline commit，不应作为 IE 新能力验收。

- `app/services/pageindex_service.py`：`build_outline_prompt(..., top_k=...)`、outline diagnostics / JSON repair diagnostics、`snapshot_outline_diagnostics()`、`merge_candidates_round_robin()`、`build_answer_context()` token budget skip、async/load structure 入口的 run reuse cache 调用。
- `app/services/chat_service.py`：chat retrieval 中的 outline diagnostics 保真、round-robin manual merge、rerank fallback 到 round-robin、execution context merge strategy 变化。
- `app/services/compliance_service.py`：compliance retrieval 中的 outline diagnostics 保真、round-robin manual merge、rerank fallback 到 round-robin、execution context merge strategy 变化。
- `pageindex/utils.py`：`RunReuseCache`、`ensure_run_reuse_cache()`、`run_reuse_scope()`、`get_page_tokens()` cache。
- `app/services/storage_service.py`：`read_json_artifact()` / MinIO read path 的 run reuse cache 使用。
- `tests/phase4/test_pageindex_retrieval_contract.py`：retrieval contract baseline tests，当前为 untracked，必须与 baseline commit 对齐后再纳入。
- `tests/phase4/test_skill_stream_runtime_contract.py`：round-robin rerank meta expectation 属于 retrieval baseline 断言。

## 不应进入本批提交的 Generated / Local 文件清单

这些文件不应进入 baseline commit 或 IE infra commit。若某个 report 需要作为 dry-run 证据，应放入单独 evidence/report commit，并在 PR 中说明来源和可复现命令。

- `.codex/config.toml`：本地 agent 配置。
- `frontend/patch-skill-chat.sh`：本地 patch 脚本，当前不属于 IE 基建边界。
- `scripts/phase47/skill_run_eval.py`：本地/评估脚本，当前未归入 IE routing asset 基建。
- `results/evaluation_results.json`
- `results/questions.json`
- `results/raw_results.json`
- `results/test_log.txt`
- `results/test_report.xlsx`
- `results/phase4_7_backend_validation_failed_20260417T062147Z.json`
- `results/phase4_7_backend_validation_latest.json`
- `results/phase4_7_backend_validation_latest_failed.json`
- `results/phase4_7_backend_validation_latest_passed.json`
- `results/phase4_7_backend_validation_passed_20260417T063036Z.json`
- `results/phase4_7_backend_validation_passed_20260417T063651Z.json`
- `results/phase4_7_backend_validation_passed_20260423T030805Z.json`
- `results/phase4_7_backend_validation_passed_20260423T100430Z.json`
- `results/routing_asset_scan*.json` 和 `results/routing_asset_backfill_rollback*.json`：如后续生成，只能作为显式 dry-run/backfill/rollback 证据单独处理。
- `spec/fastapi_service/phase4_access_and_admin_control_plane/*.md` 中当前 untracked 的历史规划/迁移/phase 文档：除非对应 PR 明确需要，否则不要夹带进本批 IE infra commit。

## 建议提交顺序

1. Baseline commit：只合并 retrieval contract baseline。包括 prompt top-k、diagnostics、round-robin merge、token budget skip、run reuse cache，以及对应 retrieval tests。不要包含 routing asset schema、embedding dark contract、backfill tool。
2. IE infra commit：合并 routing asset contract、schema/model/migration、storage/parse build hooks、telemetry、provider embedding dark contract、debug snapshot、配置示例、IE tests 和 runbook。提交说明使用 "dark contract / dry-run / deferred / read-only debug" 语义。
3. Dry-run evidence/report commit：仅在 PR 需要审计证据时追加。包含经过确认可提交的 `results/routing_asset_scan*.json`、validation JSON 或 report；不要夹带本地 eval、临时日志、`.codex/config.toml`。

## 不能描述为已上线的新能力

- 不能说 "新 routing 已上线"：当前 `routing_index.json`、`document_routing_nodes`、route docs/synthetic queries/embeddings hooks 是 artifact/schema/build readiness 基建，不是在线 router 决策面。
- 不能说 "embedding retrieval 已接入"：`SYSTEM_EMBEDDING_*` 和 provider embedding resolver 是 dark contract；默认 off，且不进入在线检索主链路。
- 不能说 "synthetic query 或 embedding backfill 已运行"：本边界任务禁止运行 backfill/rollback；工具默认 dry-run，需要显式 `--execute` 才会变更 DB。
- 不能说 "chat/compliance 搜索已切到 routing asset"：当前 chat/compliance diff 中看到的是 telemetry/diagnostics 注入和 retrieval baseline merge 策略，未体现在线 routing asset 检索替代。
- 不能把 round-robin manual merge、outline JSON repair diagnostics、token budget skip 或 run reuse cache 描述为 IE routing/embedding 功能；它们是 retrieval baseline 或 runtime baseline。

## 混在同一文件内的人工 Review Hunks

以下文件同时包含 IE 与 baseline 差异，不能整文件归类提交；需要人工按 hunk 选择。

- `app/services/pageindex_service.py`
  - IE hunks：`RoutingBuildOptions`、routing build mode normalization、routing index node collection、summary coverage、route doc/stub hook metadata、`build_routing_index_payload()`、routing asset payload normalization imports。
  - Baseline hunks：`build_outline_prompt(..., top_k=...)`、`choose_relevant_nodes()` diagnostics、`snapshot_outline_diagnostics()`、`merge_candidates_round_robin()`、`build_answer_context()` token budget skip、`ensure_run_reuse_cache()` calls in async/context/loading paths。
  - Review rule：do not merge IE routing payload hunks and retrieval prompt/merge/cache hunks in the same commit.
- `app/services/chat_service.py`
  - IE hunks：`resolve_embedding_config()` usage, `embedding_provider_telemetry`, `routing_asset_item`, `routing_asset_build_telemetry`, execution context telemetry.
  - Baseline hunks：outline diagnostics accumulation, `merge_candidates_round_robin()`, fallback mode changes, rerank diagnostics shape, merge strategy from sequential to round-robin.
  - Review rule：if baseline is not already on target branch, do not ship chat telemetry hunks together with round-robin behavior hunks without explicit reviewer approval.
- `app/services/compliance_service.py`
  - IE hunks：embedding provider telemetry, routing asset item/coverage telemetry, execution context telemetry.
  - Baseline hunks：sync and async compliance retrieval diagnostics, per-manual candidate lists, round-robin merge, rerank fallback wording/strategy.
  - Review rule：split telemetry-only hunks from retrieval selection behavior hunks.
- `app/services/storage_service.py`
  - IE hunks：`write_document_routing_index()` and `read_document_routing_index()` normalization.
  - Baseline hunks：artifact read cache via `ensure_run_reuse_cache()`.
  - Review rule：routing artifact compatibility can go with IE infra; cache changes should follow baseline/runtime cache commit.
- `app/services/runtime_observation_service.py`
  - IE hunks：routing asset debug snapshot and telemetry sanitization.
  - Potential baseline overlap：generic observation payload sanitization changes must be checked for behavior impact outside IE before inclusion.
- `app/models/document.py`
  - IE hunks：routing index fields and readiness helpers.
  - Review rule：safe to include with migration/model only if DB migration and bootstrap tests are included in the same IE infra commit.
- `app/core/config.py`
  - IE hunks：system embedding and routing build mode envs.
  - Review rule：ensure defaults remain disabled/off and no production recommendation flips them to enabled.

## 回滚边界

本任务只新增本文档。若需要回滚本任务，删除或还原 `docs/phase4_7/routing_infrastructure_merge_boundary.md` 即可；不要回滚其他 agent 的代码或结果文件。
