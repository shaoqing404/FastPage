# Phase 4.7 Runtime Validation Checklist

本文档把 `Phase 4.7 / Batch 4.7-B` 的 API integration verification 固化为可重复执行的本地链路，并作为 `Batch 4.7-C` closeout checklist 的测试入口。

范围边界：

- 只验证已落地的 `Phase 4.5` / `Phase 4.6` 控制面与 portrait 面。
- 不重开前端、compliance、audit platform、export/import 或广泛重构。
- 发现 blocker 时，先以测试暴露；只有直接阻断验证链时才允许最小产品修复。

配套 operator 步骤：

- 完整的 test user provisioning、workspace / KB / provider / PDF / skill / query / skill-chat、portrait/control-plane、cleanup 链见 [closeout_checklist.md](closeout_checklist.md)。

运行默认值：

- repo-local PDF 优先顺序：`attention-residuals.pdf` -> `2023-annual-report-truncated.pdf` -> `PRML.pdf`
- provider bootstrap 默认规则：使用当前 `.env` 兼容 `LLM_BASE_URL` / `LLM_API_KEY` 创建新的 `openai_compatible` provider，并使用 runtime 默认模型；DashScope 兼容面当前默认值为 `openai/qwen-plus`

## 1. 本地验证顺序

先跑聚合验证：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python -m unittest tests.phase4.test_phase47_api_verification
```

再跑 Phase 4 全量后端回归：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python -m unittest discover -s tests/phase4 -p 'test_*.py'
```

最后进入运行面验证脚本：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_backend_validation.py \
  --output results/phase4_7_backend_validation_latest.json
```

## 2. 覆盖矩阵

本地聚合验证 `tests.phase4.test_phase47_api_verification` 必须显式证明：

- tenant / workspace isolation：
  `GET /api/v1/workspaces` 只返回 active tenant 内可访问 workspace；`ws_tenant2` 不得出现在 `tenant_1` 上下文。
- context switch：
  `POST /api/v1/auth/context/switch` 对 `ws_ops` 成功；对跨 tenant 的 `ws_tenant2` 明确返回 `401 Workspace not in active tenant`。
- invite accept / claim：
  accept 先验证 email mismatch `403`，再验证成功 handoff；claim 成功后再次 claim 同一 invite 明确返回 `409 Invite has already been accepted`。
- workspace create：
  `POST /api/v1/workspaces` 返回新 workspace token handoff，且 caller 在新 workspace 上拥有 `founder` membership。
- platform admin visibility：
  platform admin 可见跨 tenant workspace 列表；`ws_default`、`ws_ops`、`ws_tenant2` 都应可读。
- capability enforcement：
  member 调用 `PATCH /api/v1/workspaces/{workspace_id}` 明确返回 `403 Missing workspace capability: can_edit_workspace_metadata`。
- founder / archive invariants：
  admin 调 founder transfer 明确 `403 Founder transfer is forbidden`；default workspace archive 明确 `409 Default workspace cannot be archived`。
- portrait route access control：
  无 bearer 访问 portrait 明确 `401 Missing bearer token`；API key 访问 portrait 明确 `403 Platform admin session required`；platform admin session 成功返回 portrait。

## 3. 现有补充测试

除聚合验证外，下列测试继续承担更细粒度断言：

- `tests.phase4.test_auth_context_contract`
- `tests.phase4.test_platform_router_contract`
- `tests.phase4.test_workspace_access_service`
- `tests.phase4.test_workspace_admin_service`
- `tests.phase4.test_workspace_create_contract`
- `tests.phase4.test_workspace_create_service`
- `tests.phase4.test_workspace_invite_service`
- `tests.phase4.test_phase45_invariant_constraints`

规则：

- 负路径必须是显式 status/detail 断言，不能只靠“没有成功”来推断。
- 新增 hardening 验证时，优先放入聚合验证；细节不变量继续留在现有单测。

## 4. 运行面检查项

执行 `phase4_7_backend_validation.py` 后，人工复核以下项目：

- `summary.status == "passed"`
- cleanup 结果明确
- 创建出来的 user/workspace/provider/KB/document/skill/API key id 都被记录
- portrait 结果含 explainability payload
- workspace isolation 负路径证据明确，而不是只看 happy path
- 若触发 reset-password，只记录操作事实，不落明文密码

## 5. 仍然属于运行面的问题

以下项目不能只靠本地 unittest 关闭，必须由运行面验证脚本或人工复核补足：

- MySQL + MinIO + Redis 真实 `.env` 链路
- provider `probe-models` 与真实凭据
- repo-local PDF 上传、parse/index/build、query、skill-chat 成功
- cleanup/retention 是否符合 `docs/phase4_7/verification_artifact_policy.md`

## 6. 已知限制

跨 tenant 的真实运行面负路径仍受限于 tenant 创建还不是一等操作流。

本阶段规则：

- 不用 undocumented DB 手改去伪造正常 closeout 证据。
- 如果运行面只完成了 same-tenant workspace isolation，就在 closeout 记录里明确写出这个限制。
