# Phase 4.7 Operations Manual

本目录覆盖 `Phase 4.7 / Batch 4.7-A` 到 `Batch 4.7-C` 的后端 hardening 交付，不引入新的产品功能。

这里是 `Phase 4.7` 唯一的 operator-doc 来源。

- `spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_7_pre_phase5_release_hardening.md` 负责阶段目标与范围定义。
- `spec/.../phase4_7_*` 下较早的 operator 风格文档不再作为执行入口使用。
- skill、closeout report、仓库 README 都应回指本目录。

建议按下面顺序使用：

1. [reset_runbook.md](reset_runbook.md)
2. [rebuild_and_bootstrap_runbook.md](rebuild_and_bootstrap_runbook.md)
3. [runtime_validation_checklist.md](runtime_validation_checklist.md)
4. [closeout_checklist.md](closeout_checklist.md)
5. [verification_artifact_policy.md](verification_artifact_policy.md)

配套脚本：

- [runtime_reset.py](../../scripts/phase47/runtime_reset.py)
- [validation_artifacts.py](../../scripts/phase47/validation_artifacts.py)

配套 skill：

- [.codex/skills/pageindex-phase47-validation/SKILL.md](../../.codex/skills/pageindex-phase47-validation/SKILL.md)

配套测试与仓库入口：

- [test_phase47_api_verification.py](../../tests/phase4/test_phase47_api_verification.py)
- [test_phase47_validation_defaults.py](../../tests/phase4/test_phase47_validation_defaults.py)
- [README.md](../../README.md)

范围边界：

- 这里只标准化项目自有的 MySQL 表、MinIO 前缀、repo 本地运行数据。
- 不授权清理共享基础设施中的未知数据。
- 不扩展到 `app/api/routers/*`、产品流、前端或 `Phase 5`。

当前证据：

- 当前树通过的 closeout 证据已落盘到 `results/phase4_7_backend_validation_passed_20260423T100430Z.json`
- 本次运行完成了 cleanup，且没有触发 password reset 流
- 如果仓库状态变化，需要先重新生成 `results/phase4_7_backend_validation_latest.json`，再用 `validation_artifacts.py finalize` 归档
