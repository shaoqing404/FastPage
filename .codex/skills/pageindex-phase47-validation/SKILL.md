---
name: pageindex-phase47-validation
description: Run or update PageIndex Phase 4.7 backend validation and closeout materials. Use when the task involves Phase 4.7 reset/rebuild/runtime validation, repo-local PDF selection, provider bootstrap defaults, portrait/control-plane verification, or validation artifact cleanup in this repository.
---

# PageIndex Phase 4.7 Validation

只在当前仓库的 `Phase 4.7` hardening / closeout 任务中使用本 skill。

## 必读入口

先读：

1. `docs/phase4_7/README.md`
2. `docs/phase4_7/runtime_validation_checklist.md`
3. `docs/phase4_7/closeout_checklist.md`
4. `docs/phase4_7/verification_artifact_policy.md`

需要 reset / rebuild 细节时，再读：

- `docs/phase4_7/reset_runbook.md`
- `docs/phase4_7/rebuild_and_bootstrap_runbook.md`

需要核对脚本真实行为时，再读：

- `spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_backend_validation.py`
- `scripts/phase47/validation_artifacts.py`

## 固定边界

- 只验证 `Phase 4.5` 和 `Phase 4.6` 已落地闭环。
- 不重开 invite / password / KB 设计。
- 不处理 frontend、governance、audit、export/import。
- 优先使用 repo-local PDF，不用外部 PDF 替代主链证据。

## 默认值

- 首选 PDF：`examples/documents/attention-residuals.pdf`
- 回退 PDF：`examples/documents/2023-annual-report-truncated.pdf`
- 第二回退 PDF：`examples/documents/PRML.pdf`
- provider bootstrap：使用当前 `.env` 兼容的 `LLM_BASE_URL` 与 `LLM_API_KEY`
- validation provider：始终通过产品/API 流新建 `openai_compatible` provider
- 默认模型：取 `app.core.config.default_llm_model()`；DashScope 兼容运行面当前默认值是 `openai/qwen-plus`

不要把 bootstrap 阶段的 system-managed provider 当作 4.7 validation provider 的替代证据。4.7 需要重新走 provider create + probe-models + query / skill-chat 全链路。

## 标准执行顺序

1. 先确认当前任务属于 4.7 hardening / closeout，而不是新功能开发。
2. 跑本地测试基线：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python -m unittest tests.phase4.test_phase47_api_verification
uv run python -m unittest tests.phase4.test_phase47_validation_defaults
uv run python -m unittest discover -s tests/phase4 -p 'test_*.py'
```

3. 如果任务要求运行面验证，使用标准脚本：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_backend_validation.py \
  --output results/phase4_7_backend_validation_latest.json
```

需要密码链路时再加 `--exercise-password-reset`。

4. 检查 JSON artifact 至少包含：

- `summary.status`
- `summary.source_pdf`
- `created.user_id`
- `created.workspace_id`
- `created.provider_id`
- `created.knowledge_base_id`
- `created.document_id`
- `created.skill_id`
- `created.api_key_id`
- `cleanup.status`
- `cleanup.retained_for_failure_analysis`
- `cleanup.remaining_artifacts`

5. 成功后固化并审计 artifact：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/validation_artifacts.py finalize \
  results/phase4_7_backend_validation_latest.json
```

必要时执行：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/validation_artifacts.py audit
```

## 汇报要求

输出必须明确：

- 本次使用的 repo-local PDF
- provider bootstrap 默认值与实际使用值
- 是否执行了 test user provisioning / password reset
- workspace / KB / provider / PDF / skill / query / skill-chat 是否全链路通过
- portrait / control-plane 是否通过
- cleanup 是否完成，还是为失败排障而保留
- 哪些限制仍存在，但不属于 4.7 重新设计范围

如果 cross-tenant 真实运行面负路径没有执行，不要补造证据；直接在结论中写明它仍受 tenant 创建流程限制。
