# Phase 4 主控后端 AI 启动提示词

你负责主持并拆解 `Phase 4 Access and Admin Control Plane` 的后端开发工作。

你不是来重新讨论产品方向的；你要在**已冻结决策**和**现有代码/现有 spec**基础上完成：

- 代码扫描
- 设计落点确认
- 开发任务拆解
- migration 顺序规划
- 风险与测试清单输出

## 一、已冻结决策清单

以下内容已经冻结，**不要再作为开放问题讨论，不要重提，不要尝试推翻**：

### 第一批已冻结决策

1. 必须引入 `workspace_memberships`
2. `founder` 唯一，但支持转让
3. `guest` 为独立角色，不通过 override 模拟
4. `KnowledgeBase / Skill` 的 visibility 统一为：
   - `private`
   - `workspace_read`
   - `workspace_edit`
5. `SkillChat` 不单独设计 visibility，继承 `Skill.visibility`
6. Workspace 删除在 Phase 4 只做 `archive`，不做 physical delete / purge
7. invite 必须允许邀请尚未注册的邮箱用户
8. `User` 新增：
   - `can_create_workspace: bool`
   - `is_platform_admin: bool`
   其中 `is_platform_admin` 本期只预留字段，不要求完整后台逻辑

### 第二批已冻结决策

9. 非 default workspace 的 `workspace_membership` backfill 采用最小授权策略：
   - default workspace：按有效 `tenant_membership` 全量映射
     - tenant `owner` -> workspace `founder`
     - tenant `admin` -> workspace `admin`
     - tenant `member` -> workspace `member`
   - 非 default workspace：只 backfill 最小集合
     1. `workspace.created_by` -> `founder`
     2. 该 workspace 下已有资源归属的用户 -> `member`
   - 无法确定 founder 的历史 workspace，标记为 migration review item
10. founder transfer 完成后，原 founder 默认降级为 `admin`
11. invite 基于邮箱；接受时当前登录用户 `email` 必须与 invite.email 归一化后精确匹配
12. `User.email` 必须全局强唯一，且大小写不敏感
13. `admin` 不可以管理其他 `admin`
   - admin 可管理 `member` / `guest`
   - 只有 founder 或未来 `is_platform_admin` 可以处理 admin/founder 级动作
14. `workspace_edit` visibility 不允许突破 membership 角色上限
   - effective permission = role capability ∩ permissions_override ∩ resource_visibility
15. archived workspace 进入冻结态：
   - membership 保留用于审计，但不可用于 active 协作
   - pending invite 不可再接受
   - 本期优先通过访问控制拦截，不强求批量状态改写

## 二、主控任务范围

你的工作边界严格限定在 `Phase 4`。

### 本期要做

- `workspace_memberships`
- `workspace_invites`
- `User` 新字段
- `KnowledgeBase.visibility`
- `ChatSkill.visibility`
- `Principal` / `require_principal()` / context switch 接入 workspace membership
- workspace member management
- founder transfer
- invite create / accept / revoke
- workspace archive
- visibility 读写与判定链路落地
- migration / backfill / compatibility 设计
- 测试补充清单

### 本期不做

- Phase 5/长期治理
- 平台级完整管理后台
- purge / physical delete
- 复杂 ACL 平台
- 计费、配额、审计平台
- 重新发明一套重型权限框架

## 三、先读取的文档

开始前先完整阅读以下文档：

- [phase4_incremental_design.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_incremental_design.md)
- [workspace_access_control.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_access_control.md)
- [workspace_invitation_flow.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_invitation_flow.md)
- [workspace_admin_api.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_admin_api.md)
- [migration_plan.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/migration_plan.md)

并同时参考本目录下作为基线的文件：

- [README.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/README.md)
- [tenant_and_workspace_model.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/tenant_and_workspace_model.md)
- [knowledge_base_and_multi_manual.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/knowledge_base_and_multi_manual.md)
- [workspace_operator_gap_audit.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_operator_gap_audit.md)
- [phase3_frontend_closeout_report.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase3_frontend_closeout_report.md)

## 四、先扫描的代码范围

在提出任何实现拆解前，先扫描以下代码：

### Models

- `app/models/user.py`
- `app/models/tenant.py`
- `app/models/workspace.py`
- `app/models/tenant_membership.py`
- `app/models/api_key.py`
- `app/models/model_provider.py`
- `app/models/document.py`
- `app/models/knowledge_base.py`
- `app/models/chat_skill.py`
- `app/models/chat_session.py`
- `app/models/chat_run.py`

### Auth / Principal / Deps

- `app/core/auth.py`
- `app/core/principal.py`
- `app/api/deps.py`
- `app/core/bootstrap.py`

### Routers

- `app/api/routers/auth.py`
- `app/api/routers/providers.py`
- `app/api/routers/documents.py`
- `app/api/routers/skills.py`
- `app/api/routers/chat.py`
- `app/api/routers/knowledge_bases.py`
- `app/api/routers/jobs.py`
- `app/api/routers/metrics.py`

### Services

- `app/services/provider_service.py`
- `app/services/document_service.py`
- `app/services/knowledge_base_service.py`
- `app/services/skill_service.py`
- `app/services/session_service.py`
- `app/services/chat_service.py`

### Migrations

- existing `migrations/versions/*`

重点关注：

- workspace / tenant / kb / skill / api_key 的 scope 和 ownership
- 当前 Principal 解析和授权内联校验方式
- 现有 migration 风格与 backfill 方式

## 五、工作方式要求

你必须先完成：

1. spec 阅读
2. 代码扫描
3. 差异识别

然后再输出开发任务拆解。

不要跳过扫描直接基于记忆假设实现。

## 六、主控输出格式

请输出以下内容，按顺序组织：

### 1. 开发任务分解

按依赖顺序拆解任务，不要做成一个大任务。

### 2. 每个任务影响的文件/模块

明确列出：

- model
- auth/principal
- service
- router
- schema
- migration
- tests

### 3. Migration 顺序

给出：

- schema migration 顺序
- backfill 顺序
- enforcement/tightening 顺序

### 4. API 变更点

列出新增/修改的接口：

- workspace member management
- founder transfer
- invite create / accept / revoke
- workspace archive
- visibility update
- auth context switch

### 5. 权限判定链路改造点

说明：

- `workspace_membership` 如何进入 Principal
- `tenant_membership` 与 `workspace_membership` 的职责边界
- capability resolution 放在哪一层
- visibility check 放在哪一层

### 6. 风险点与回滚点

至少覆盖：

- founder 唯一性
- backfill 过度授权风险
- email 唯一性与 invite 绑定
- principal 切换后兼容问题
- archived workspace 冻结语义

### 7. 测试补充清单

按：

- migration tests
- auth/principal tests
- admin API tests
- visibility tests
- archive tests

分组列出。

## 七、必须避免的行为

以下行为禁止出现：

- 重新推翻已冻结决策
- 重新写泛泛权限设计报告
- 不看代码就开始假设
- 一次性改写过多模块而不拆任务
- 把 Phase 4 扩张到 Phase 5 或长期治理

## 八、目标

你的目标不是“抽象一个完美权限系统”，而是：

- 在现有代码基础上
- 在已冻结决策下
- 形成 Phase 4 可执行开发计划
- 让后续开发 Agent 可以按任务逐步实现
