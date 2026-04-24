# Routing Infrastructure Integration Scope

本文档用于本批 IE 基建增强的提交边界控制，避免把已有 retrieval baseline 修复误归入 routing/embedding 基建。

## IE 基建提交范围

可归入本批的变更类型：

- system embedding provider dark contract、配置、capability detection、resolver 和 telemetry。
- routing asset v1 schema/readiness contract、legacy artifact normalization、storage read/write compatibility。
- parse/build pipeline 的 routing asset metadata、summary coverage、route-doc/synthetic/embedding hook stub，默认 disabled 或 dry-run。
- routing asset build / provider fallback / coverage / missing / failure telemetry。
- 只读 debug 输出、dry-run/backfill/rollback 工具和 runbook。
- 配置示例、README、运维文档中与上述 contract 对齐的说明。

## 不归入 IE 基建的 retrieval baseline

以下差异属于既有检索契约或 Phase 4.10 baseline 修复，不应作为 IE 基建的新能力来描述或验收：

- `build_outline_prompt(..., top_k=...)` 的 prompt 上限修正。
- `merge_candidates_round_robin()` 及 chat/compliance 的 round-robin fallback 行为。
- outline diagnostics / JSON repair diagnostics 的 runtime 保真。
- `build_answer_context()` 的 token budget skip 行为。
- `ensure_run_reuse_cache()` 相关 runtime cache 修正。
- `parse_pdf_to_structure()` 不再强制关闭 node summary 的行为。

如果这些 baseline 修复仍未进入目标分支，应先单独合并为 retrieval contract baseline，再合并 IE 基建；否则 IE 批次会被误认为修改了在线搜索主链路。

## Commit / PR Hygiene

- 不提交 `results/routing_asset_scan*.json` 或 `results/routing_asset_backfill_rollback*.json`，除非 PR 明确把它们作为审计证据附件。
- 不把 `routing_index.json` 的生成能力描述成在线 router 已启用。
- 不把 `SYSTEM_EMBEDDING_*` 描述成 embedding retrieval 已接入；它只是 provider dark contract。
- 不把 `ROUTING_*_BUILD_MODE=enabled` 作为默认值或生产推荐值。
