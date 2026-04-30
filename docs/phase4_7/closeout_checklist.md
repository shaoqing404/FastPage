# Phase 4.7 End-to-End Closeout Checklist

本文档把 `Phase 4.7 / Batch 4.7-C` 的运行面 closeout 链固化成 operator 可重复执行的步骤。

工作目标：

- 用 repo-local PDF 先完成 `Phase 4.5` 已落地闭环的再验证
- 明确当前 `.env` 兼容 runtime 的 provider bootstrap 默认规则
- 补齐 portrait / control-plane 验证与 cleanup 收口

范围边界：

- 只验证 `Phase 4.5` / `Phase 4.6` 已落地能力
- 不重做 invite / password / KB 设计
- 不扩展到 frontend、governance、audit、export/import

## 1. 输入与默认值

优先 PDF 规则：

1. `examples/documents/attention-residuals.pdf`
2. `examples/documents/2023-annual-report-truncated.pdf`
3. `examples/documents/PRML.pdf`

执行规则：

- 默认先用 repo-local PDF；只有主选文件不可用或需要补充覆盖时才切换到同仓库其他 PDF。
- 不用外部临时 PDF 替代 closeout 主链证据。

provider bootstrap 规则：

- 使用当前 `.env` 兼容的 `LLM_BASE_URL` 与 `LLM_API_KEY` 作为验证输入。
- 通过产品/API 流创建一个新的 `openai_compatible` validation provider，而不是把 bootstrap 期间的 system-managed provider 当作替代证据。
- 默认模型取当前 runtime 默认值；当 `LLM_BASE_URL` 指向 DashScope 兼容面时，当前默认值是 `openai/qwen-plus`。
- 成功标准不仅是 provider 创建成功，还要包含 `probe-models` 成功与后续 query / skill-chat 成功。

## 2. 进入 closeout 前

先完成下列前置动作：

1. 按 [reset_runbook.md](reset_runbook.md) 完成安全 reset。
2. 按 [rebuild_and_bootstrap_runbook.md](rebuild_and_bootstrap_runbook.md) 完成 rebuild 与 bootstrap。
3. 运行本地 hardening 基线：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python -m unittest tests.phase4.test_phase47_api_verification
uv run python -m unittest tests.phase4.test_phase47_validation_defaults
uv run python -m unittest discover -s tests/phase4 -p 'test_*.py'
```

说明：

- 前两个命令是当前树上相对稳定的门禁
- 最后一个 blanket `discover` 目前已知存在顺序敏感性；不要把它当作单独的通过条件

4. 确认 backend API、worker、MySQL、MinIO、Redis 都已连到当前目标环境。

## 3. Test User Provisioning

1. platform admin 登录。
2. 创建临时 validation user，命名遵循 `phase47_val_<suffix>`。
3. 记录 user id、email、创建时间；不要把明文密码写入 repo 文件。
4. 如本次需要补验密码链路，执行 reset-password，然后立即完成 change-password，只记录动作事实和时间。
5. 用 validation user 登录，确认拿到 default workspace 上下文。

## 4. Workspace / KB / Provider / PDF / Skill / Query / Skill-Chat 链

按下面顺序执行，不能跳步：

1. validation user 创建 validation workspace，并确认 token 自动切到新 workspace。
2. 创建临时 API key，随后用它访问 platform route，确认 `403`，避免把 API key 误当作 platform session。
3. 创建 knowledge base。
4. 创建 validation provider：
   使用 `.env` 兼容的 `base_url`、`api_key` 与 runtime 默认模型。
5. 对 validation provider 执行 `probe-models`。
6. 上传优先 PDF，并确认 `uploaded_via_kb_id` 指向当前 KB。
7. 触发 parse/index/build，直到 document 进入 `index_ready`。
8. 把 document 绑定进 knowledge base。
9. 创建绑定该 KB 和 provider 的 skill。
10. 先做一次 direct query，再做一次 skill-chat。
11. 读取 session messages，确认链路里至少存在 user/assistant 往返消息。

建议直接使用标准脚本：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_backend_validation.py \
  --output results/phase4_7_backend_validation_latest.json
```

如需补验密码重置链路：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_backend_validation.py \
  --exercise-password-reset \
  --output results/phase4_7_backend_validation_latest.json
```

## 5. Portrait / Control-Plane Verification

closeout 证据必须同时覆盖以下项目：

1. platform admin 仍可读取 tenant list、user list、workspace control-plane 数据。
2. API key 访问 platform user list / portrait 明确返回 `403`。
3. user access portrait 返回正确的 user id，并带 `effective_portrait.resolved_context.workspace_id`。
4. workspace access portrait 返回正确的 workspace id，并带 explainability / invariant 信息。
5. `active_founder_invariant_ok` 为真。
6. 从非 owning workspace 访问 validation document 明确返回 `404`，作为 workspace isolation 负路径证据。

注意：

- `Phase 4.7` 只验证 `Phase 4.6` 已落地 portrait 输出，不新增 portrait 字段。
- cross-tenant 真实运行面负路径仍受 tenant 创建非一等操作流限制；若本次未覆盖，必须在结果中显式记录限制，而不是伪造证据。

## 6. Cleanup 与归档

验证成功后按固定顺序清理：

1. revoke 临时 API key
2. delete 临时 skill
3. delete 临时 document
4. delete 临时 knowledge base
5. delete 临时 provider
6. archive 临时 workspace
7. disable 临时 validation user

验证失败时：

- 默认保留已创建工件用于排障
- 如临时 API key 仍处于活跃风险状态，可先单独 revoke
- 在 JSON artifact 中把 `retained_for_failure_analysis` 标明为真

每次运行后都执行：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/validation_artifacts.py finalize \
  results/phase4_7_backend_validation_latest.json
```

如需检查当前 `results/` 中的保留情况：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/validation_artifacts.py audit
```

## 7. Closeout 结论最少要回答的问题

最终汇报至少要明确：

- 本次使用了哪个 repo-local PDF
- provider bootstrap 默认值是什么，是否走了 `.env` 兼容链路
- test user provisioning 是否完成，是否触发了 reset-password
- workspace / KB / provider / PDF / skill / query / skill-chat 是否全链路通过
- portrait / control-plane 验证是否通过
- cleanup 是完成、部分完成，还是为了排障而保留
- 哪些限制仍然存在，但不属于本阶段重新设计范围

当前树证据：

- `results/phase4_7_backend_validation_passed_20260423T100430Z.json`
- cleanup 已完成
- `password_reset_flow.performed` 为 `false`
