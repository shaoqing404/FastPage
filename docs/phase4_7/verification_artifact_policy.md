# Phase 4.7 Verification Artifact Policy

本文档定义 `Phase 4.7` 运行面验证产物的命名、清理顺序和保留规则，目的是把原本临时性的 closeout 证据变成可复核、可清理的标准流程。

## 1. 命名规则

临时运行面验证实体统一使用 `phase47` 前缀：

- 用户名：`phase47_val_<suffix>`
- 邮箱：`phase47+<timestamp>@example.test`
- workspace slug：`phase47-validation-<suffix>`
- provider 名称：`phase47-validation-provider-<suffix>`
- KB 名称：`Phase47 Validation KB <suffix>`
- skill 名称：`Phase47 Validation Skill <suffix>`
- API key 名称：`phase47-validation-key-<suffix>`

验证 JSON 文件采用两层命名：

1. 工作中的默认输出：
   - `results/phase4_7_backend_validation_latest.json`
2. 归档后的规范文件名：
   - `results/phase4_7_backend_validation_passed_<UTC时间戳>.json`
   - `results/phase4_7_backend_validation_failed_<UTC时间戳>.json`

推荐在每次运行 `spec/.../phase4_7_backend_validation.py` 后立刻执行：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/validation_artifacts.py finalize \
  results/phase4_7_backend_validation_latest.json
```

该脚本会：

- 从 `latest.json` 生成带状态和 UTC 时间戳的规范文件名
- 刷新 `phase4_7_backend_validation_latest_passed.json` 或 `..._latest_failed.json`
- 按保留规则清理超期的旧 JSON 证据

## 2. 密码与敏感信息规则

允许：

- 运行脚本时在进程内短暂持有临时密码
- 只在操作者明确选择 reset-password 验证时，在终端中一次性显示临时密码

禁止：

- 在 Markdown 文档中记录明文密码
- 在 `results/` 中保存明文密码
- 把临时密码提交进 git

若执行了 reset-password，仅记录：

- 目标 user id
- reset 时间
- 触发者 id
- 后续 change-password 是否成功

## 3. 成功后的清理顺序

验证成功后按下面顺序清理：

1. revoke 临时 API key
2. delete 临时 skill
3. delete 临时 document
4. delete 临时 knowledge base
5. delete 临时 provider
6. archive 临时 workspace
7. disable 临时 validation user

理由：

- provider 删除通常依赖下游对象先清空
- workspace archive 应发生在 workspace 内对象清理之后
- `Phase 4.x` 不引入 user/workspace 的物理 purge 规则

## 4. 失败后的保留规则

如果验证中途失败：

- 不做广泛清理
- 保留已创建实体用于排障
- 在 JSON 中写明 `retained_for_failure_analysis=true`
- 若临时 API key 仍处于活跃状态且存在风险，可单独立即 revoke

## 5. 默认保留窗口

默认窗口如下：

- 最近的通过 JSON：至少保留 14 天，并保留到下一次成功运行生成新证据
- 最近的失败 JSON：至少保留 14 天，并保留到问题被定位且被新证据替代
- 已禁用的 validation user 与已归档的 validation workspace：保留到下一次 clean reset 周期

局部文件清理建议交给脚本执行，而不是人工挑文件删除：

```bash
cd "$(git rev-parse --show-toplevel)"
uv run python scripts/phase47/validation_artifacts.py audit
```

## 6. 必须写入 JSON 的字段

每个验证 JSON 都必须能明确回答：

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

## 7. 范围边界

本规则只覆盖 `Phase 4.7` 的 closeout 证据和临时验证产物。

它不负责：

- 长期治理留存系统
- 跨实例归档策略
- `Phase 5` 的审计中心能力
