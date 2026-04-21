# Phase 4.7 Rebuild And Bootstrap Runbook

本文档定义 reset 之后如何把环境重建到：

- migration-ready
- bootstrap-ready

这里不引入新功能，只标准化重建步骤和验证点。

## 1. 输入条件

执行本 runbook 前，应该已经完成：

- [reset_runbook.md](reset_runbook.md) 中需要的清理
- `.env` 已指向目标运行面
- 依赖已安装，`uv` 可用

## 2. 重建步骤

先执行 bootstrap 驱动的迁移与初始化：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/runtime_reset.py rebuild
```

这个动作会：

- 调用 `app.core.bootstrap.init_db()`
- 先跑 Alembic 到 `head`
- 再写入默认 tenant / admin / default workspace / membership
- 输出当前 `alembic_version` 与 bootstrap-ready 摘要

## 3. 期望结果

`rebuild` 成功后，应满足：

- `alembic_version == 20260416_0010`
- 默认 tenant 存在：`tenant_default`
- 默认 admin 用户存在，并且：
  - `is_platform_admin == true`
  - `can_create_workspace == true`
  - `is_active == true`
- 默认 workspace 存在且：
  - `is_default == true`
  - `status == active`
- 默认 admin 的 auth context 能解析到默认 workspace

## 4. 补充校验

运行与 reset/rebuild 直接相关的本地测试：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python -m unittest tests.phase4.test_bootstrap_init_db tests.phase4.test_migrations_smoke
```

如果环境有 Alembic CLI，也建议检查：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run alembic heads
uv run alembic current
```

期望：

- 单一 head：`20260416_0010`
- current revision：`20260416_0010`

## 5. 进入 live validation 前的基线

在执行运行面验证脚本前，确认：

- 不存在上一次验证残留的临时用户 / workspace / provider / document
- 默认 bootstrap admin 能正常登录
- 当前环境已经是“空但有效”的基线

## 6. 失败处理

如果 `rebuild` 失败：

- 不要转去修改产品逻辑或加新 feature
- 先确认失败点是在 migration 还是 bootstrap
- 保留失败现场，避免边跑边手工改库

如果本地测试失败：

- 先修正 reset/rebuild 假设的偏差
- 不要把 `Phase 4.7-A` 扩展成产品面需求
