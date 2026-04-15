# Phase 4.5 Closeout, Management, and Control

## 1. 定位

`Phase 4.5` 是 `Phase 4 Access and Admin Control Plane` 的收尾阶段。

它不是重新定义 `Phase 4`，也不是提前进入 `Phase 5`。

本阶段的职责只有三类：

- 收尾：补齐 Phase 4 已冻结但尚未彻底闭环的后端和产品缺口
- 管理：把 Phase 4 选择性后置的管理页面和配套 API 明确纳入可执行范围
- 控制：补齐平台级最小控制面，使 `workspace` / `user` / `context` 从“可用”变成“可运营”

边界上：

- `Phase 4` 解决的是 workspace access/admin 主干能力
- `Phase 4.5` 解决的是这些能力的收口、管理面、控制面、兼容债清理
- `Phase 5` 才进入审计、治理、长期运营、配额/策略/报表等长期平台能力

## 2. 输入前提

本文件基于 `Phase 4` 的**实际代码状态**，不是只基于原始 spec。

主要参考：

- [phase4_incremental_design.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_incremental_design.md)
- [workspace_access_control.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_access_control.md)
- [workspace_invitation_flow.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_invitation_flow.md)
- [workspace_admin_api.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_admin_api.md)
- [migration_plan.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase4_access_and_admin_control_plane/migration_plan.md)

以及实际代码：

- [auth.py](/Users/shaoqing/workspace/PageIndex/app/core/auth.py)
- [principal.py](/Users/shaoqing/workspace/PageIndex/app/core/principal.py)
- [workspace_access_service.py](/Users/shaoqing/workspace/PageIndex/app/services/workspace_access_service.py)
- [workspace_admin_service.py](/Users/shaoqing/workspace/PageIndex/app/services/workspace_admin_service.py)
- [workspace_invite_service.py](/Users/shaoqing/workspace/PageIndex/app/services/workspace_invite_service.py)
- [workspace_scope_service.py](/Users/shaoqing/workspace/PageIndex/app/services/workspace_scope_service.py)

## 3. Phase 4 已完成的基线

以下内容默认视为已在 `Phase 4` 落地，不在 `Phase 4.5` 重新设计：

- `workspace_memberships`
- `workspace_invites`
- `KnowledgeBase.visibility`
- `ChatSkill.visibility`
- `Principal` 中的 tenant + workspace membership 双层解析
- `workspace_permissions` capability 计算
- workspace 成员管理
- founder transfer
- workspace archive
- invite create / accept / revoke
- `POST /api/v1/auth/context/switch`
- `jobs` / `metrics` 的 workspace scope 收口

`Phase 4.5` 的出发点是：

- 这些主链路已经有了
- 但仍有若干**数据库级约束未收紧**
- 若干**产品闭环未补齐**
- 若干**平台管理面被故意后置**
- 若干**兼容路径仍在使用 `User.tenant_id` 作为过渡字段**

## 4. Phase 4.5 目标

### 4.1 收尾目标

把 `Phase 4` 从“主路径已实现”推进到“关键约束更硬、关键闭环更完整、关键兼容债更少”。

### 4.2 管理目标

把此前后置的管理页面及其后端 contract 纳入正式范围，包括：

- workspace 发现与切换辅助面
- workspace 创建与自助管理入口
- 平台级用户/工作区管理页面
- 平台级最小控制后台

### 4.3 控制目标

建立一个**轻量但真实可用**的平台控制面：

- 能看
- 能管
- 能收口关键操作

但不扩张成完整治理平台。

## 5. 本阶段明确要做的内容

### 5.1 数据约束与迁移收紧

#### A. `User.email` 真正收口

目标状态：

- `User.email` 全局唯一
- 大小写不敏感
- invite 的 email 归一化规则与 `User.email` 保持一致

本阶段需要完成：

- 现网数据探测和重复值处理策略
- 统一 normalization 规则
  - `trim`
  - `lower-case`
- 数据库层唯一约束或等价可执行方案
- 测试覆盖

说明：

- `Phase 4` 已经在 invite 侧按规范化值工作
- 但 `User.email` 仍未完成数据库级强约束
- 这在本阶段不能继续作为开放问题拖延

#### B. active founder 唯一性落到数据库或等价硬约束

目标状态：

- 每个 workspace 同时只能有一个 `active founder`

本阶段需要完成：

- 明确方言兼容策略
- 在支持的数据库上落数据库约束
- 在无法优雅统一的方言上提供可验证的等价防守
- founder transfer 与成员 API 不得破坏该约束

说明：

- `Phase 4` 当前主要依赖服务层
- `Phase 4.5` 需要把这件事从“主要靠应用逻辑”提升到“有硬约束支撑”

#### C. invite 唯一性与过期策略硬化

目标状态：

- 同一 workspace 下，同一 normalized email，同时只有一个 `pending` invite

本阶段需要完成：

- 数据库侧或等价强保证方案
- `expired` / `revoked` / `accepted` 的一致行为验证

### 5.2 Context 与 discoverability 闭环

#### A. workspace list / switch discoverability

`Phase 4` 已有：

- `POST /api/v1/auth/context/switch`

但仍缺：

- “我能切换到哪些 workspace”的正式后端 contract

本阶段要补：

- `GET /api/v1/workspaces`
  - 返回当前 session user 在当前 active tenant 下可进入的 workspace
  - 明确 active / default / archived 状态
- 如产品确认需要，可补：
  - `GET /api/v1/workspaces/{workspace_id}`
  - `GET /api/v1/auth/context`

目标：

- 前端不再依赖登录时缓存的一次性 workspace 信息
- workspace switcher 有正式数据来源

#### B. invite accept 与 context handoff 收口

`Phase 4` 已实现 invite accept 后的新 token/context 返回。

本阶段要补：

- 与 workspace list / context contract 对齐
- 保证跨 tenant invite accept 后的后续登录/刷新行为一致
- 明确 `User.tenant_id` 在 Phase 4.5 仍只是兼容字段，而非权限真相

### 5.3 兼容债清理

本阶段要继续清理仍依赖 `User.tenant_id` 作为行为主导的内部路径。

至少包括：

- [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py#L398)
- [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py#L418)
- [chat_service.py](/Users/shaoqing/workspace/PageIndex/app/services/chat_service.py#L556)

目标：

- 降低 compat 字段对 runtime 行为的影响
- 让 `Principal` / membership 成为主事实来源

说明：

- `User.tenant_id` 在 Phase 4.5 仍可保留
- 但它必须逐步退化为登录兼容和历史兼容字段
- 不能继续成为新逻辑的授权真相来源

### 5.4 Workspace 自助创建与控制

`Phase 4` 已新增：

- `User.can_create_workspace`

但该字段尚未形成真实能力闭环。

本阶段要补：

- workspace create API
- `can_create_workspace` 的真实控制语义
- workspace create 后的默认 founder / membership / context 行为
- 前端自助创建入口

基本规则：

- 只有 `can_create_workspace=true` 的用户可自助创建 workspace
- `is_platform_admin` 可旁路创建
- 创建后的 actor 成为新 workspace founder
- 创建后要能直接进入新 workspace

说明：

- 本阶段不要求重做 tenant 基础模型
- 但 workspace creation 不能再停留在 bootstrap-only 或管理员手工数据层面

### 5.5 平台级最小管理后台

这是 `Phase 4` 明确后置、但 `Phase 4.5` 要接回来的部分。

目标不是“长期治理平台”，而是“最小可运营的平台管理后台”。

#### A. 平台级用户管理

至少需要：

- 用户列表页所需后端 API
- 用户详情页所需后端 API
- 用户状态控制
  - `is_active`
- 用户能力控制
  - `can_create_workspace`
  - `is_platform_admin`
- 用户 email / username / tenant 关系可见性

可接受的操作范围：

- enable / disable user
- 调整 `can_create_workspace`
- 调整 `is_platform_admin`

本阶段不做：

- 完整审批链
- SSO / SCIM
- 外部身份治理

#### B. 平台级 workspace 管理

至少需要：

- 全局 workspace 列表页所需后端 API
- workspace 详情页所需后端 API
- 查看 founder / members / invites / archive 状态
- 平台 admin 级别的辅助控制操作

建议纳入：

- archive / unarchive workspace
- 平台 admin 触发 founder transfer
- 平台 admin 查看 archived workspace

说明：

- `Phase 4` 已有 founder/admin 邻域内的 workspace admin plane
- `Phase 4.5` 补的是跨 workspace、跨 tenant 的平台管理视角

#### C. 平台级 tenant / workspace directory

如果当前产品仍保留 tenant 作为一级边界，则本阶段至少补：

- tenant list
- tenant detail 中的 workspace/user 概览

但不做：

- 配额治理
- 账单视图
- 审计报表
- 复杂租户策略

### 5.6 前端页面补齐

`Phase 4.5` 明确包含前端页面收尾，但要求与现有主题统一，不引入新的视觉体系。

至少要完成：

#### A. Workspace 侧页面

- workspace switcher
- workspace settings / admin page
- members management page
- invites management page
- founder transfer UI
- archive UI
- workspace create page

#### B. Resource 侧页面

- Knowledge Base visibility 配置面
- Skill visibility 配置面
- 对 capability / visibility 被拒绝的前端反馈

#### C. Invite 侧页面

- invite accept page
- invite accept 成功后的 token/context 替换流程

#### D. 平台管理侧页面

- platform users page
- platform user detail/edit page
- platform workspaces page
- platform workspace detail page

说明：

- 这些页面是 `Phase 4` 选择性后置的管理页面
- `Phase 4.5` 要把它们正式纳入范围
- 但页面实现仍应尽量复用已有 layout、导航、auth client、主题变量

### 5.7 开发环境清理与初始化前置 gate

`Phase 4.5` 开始实施前，必须先把开发/验证环境清到“可重新初始化”的干净状态。

本阶段要求：

- 清理远端 MySQL `pageindex` schema 中**仅由本仓库管理**的项目数据
- 不删除同库或同实例中的未知/非本项目数据
- 清理本项目 MinIO bucket/prefix 下的对象
- 清理本地 SQLite 与本项目 runtime data

原则：

- 目标是“空但有效”
- 不做粗暴的全实例删除
- 清理后的环境应能直接进入 migration + bootstrap + API 测试

### 5.8 全链路 closeout 测试要求

`Phase 4.5` 不是以“单接口通过”为结束，而是以完整链路验证为结束。

本阶段至少需要验证：

1. platform admin 登录
2. platform admin 创建或启用测试用户
3. 测试用户登录
4. 测试用户创建 workspace
5. 测试用户创建知识库
6. 测试用户使用项目 `.env` 的兼容 OpenAI 配置创建百炼 provider
7. 默认模型使用 `qwen3.5-plus`
8. 测试用户上传项目目录内 PDF
9. parse / index / build 成功
10. 创建 skill 并绑定 KB
11. 完成 query / skill chat
12. 验证 tenant / workspace / capability API 隔离

说明：

- `Phase 4.5` 不要求开放 public signup
- 测试用户由 platform admin provision 即可
- closeout 测试优先使用项目目录内 PDF，而不是外部不稳定样本

## 6. 本阶段明确不做的内容

以下内容全部留给 `Phase 5` 或更后阶段：

- audit platform
- long-term governance
- 审计报表与审计中心
- quota / billing / chargeback
- 策略引擎、审批流、治理流程
- organization / team tree / department model
- purge / physical delete
- 重型 ACL 平台
- 平台级长期运营分析报表
- 合规治理平台化

同时，本阶段也不建议扩张到：

- 重新发明身份系统
- 外部邮件基础设施重构
- 跨系统 IAM 集成

## 7. API 与能力新增建议

本阶段建议新增或补齐的 contract：

### 7.1 Workspace 自助与 discoverability

- `GET /api/v1/workspaces`
- `GET /api/v1/workspaces/{workspace_id}` 可选
- `POST /api/v1/workspaces`

### 7.2 平台用户管理

- `GET /api/v1/platform/users`
- `GET /api/v1/platform/users/{user_id}`
- `PATCH /api/v1/platform/users/{user_id}`

### 7.3 平台 workspace 管理

- `GET /api/v1/platform/workspaces`
- `GET /api/v1/platform/workspaces/{workspace_id}`
- `POST /api/v1/platform/workspaces/{workspace_id}/archive`
- `POST /api/v1/platform/workspaces/{workspace_id}/unarchive`
- `POST /api/v1/platform/workspaces/{workspace_id}/founder-transfer`

### 7.4 Tenant / directory 只读视图

- `GET /api/v1/platform/tenants`
- `GET /api/v1/platform/tenants/{tenant_id}`

说明：

- API 名称可在实现时微调
- 但“workspace discoverability、自助创建、平台用户管理、平台 workspace 管理”这四类能力不应再被后置

## 8. 实施顺序建议

### Batch 4.5-A: 约束收紧

- `User.email` normalization + unique
- founder unique hardening
- invite pending unique hardening
- migration 验证

### Batch 4.5-B: discoverability 与 compat cleanup

- `GET /api/v1/workspaces`
- context contract 收口
- `User.tenant_id` compat 清理

### Batch 4.5-C: workspace create

- create workspace
- `can_create_workspace` 真正接入
- 创建后 founder/context 行为

### Batch 4.5-D: platform admin backend

- users list/detail/patch
- workspaces list/detail/control
- tenant directory read-only

### Batch 4.5-E: frontend closeout

- workspace switcher
- workspace admin pages
- invite accept page
- visibility UI
- platform admin pages

### Batch 4.5-F: environment reset and closeout chain

- 环境清理脚本或 runbook
- 干净初始化流程
- API 全链路验证
- 形成 4.5 closeout 结果

## 9. 风险点

### A. 约束收紧风险

- `User.email` 收紧可能撞到历史脏数据
- founder unique 落库时可能撞到迁移期异常状态

### B. compat cleanup 风险

- 过早删除 `User.tenant_id` 依赖可能影响历史路径
- 过晚删除则会让 Phase 4.5 的新控制面继续建立在兼容事实之上

### C. 管理后台扩张风险

- 若把 platform admin 做成“什么都能做”的大后台，会直接侵入 `Phase 5`
- `Phase 4.5` 必须坚持 operational control，而不是 long-term governance

### D. 前后端收口风险

- 如果后端 contract 继续不稳定，前端页面会重复返工
- 所以本阶段应先稳定 API，再大面积铺前端页面

### E. 清理与重建风险

- 若远端 MySQL/MinIO 清理边界不清，会误伤共享环境中的非本项目数据
- 若环境清理未标准化，后续验证结论不可重复

## 10. 验收标准

`Phase 4.5` 完成的最低标准：

### 10.1 后端

- `User.email` 达到全局唯一 + case-insensitive 目标状态
- active founder 唯一性不再只靠服务层
- `GET /api/v1/workspaces` 可驱动 workspace switcher
- workspace create 闭环可用
- `can_create_workspace` 形成真实能力
- `is_platform_admin` 不再只是轻量旁路，而是支撑最小平台控制面
- 关键 compat 路径不再继续以 `User.tenant_id` 为主事实来源

### 10.2 前端

- 用户可以发现并切换可进入的 workspace
- 用户可以在统一主题下完成 workspace 成员/邀请/归档操作
- 用户可以设置 KB / Skill visibility
- 允许创建 workspace 的用户可以完成自助创建
- 平台 admin 可以通过后台页面管理用户和 workspace

### 10.3 范围纪律

- 未把审计与长期治理混入 `Phase 4.5`
- 未把 purge / billing / quota / policy engine 混入 `Phase 4.5`
- 管理页面与后端 contract 保持一一对应，而不是做无后端支撑的空壳页面

### 10.4 closeout 验证

- 开发/验证环境可被安全清理到空初始化状态
- 可从干净状态完成 migration 与 bootstrap
- 可完成 platform admin -> test user -> workspace -> KB -> provider -> PDF -> query 的完整链路
- API 层 tenant / workspace / capability 测试覆盖关键授权边界
- 本阶段 closeout 结果可作为 `Phase 4.7` 测试标准的输入

## 11. 与 Phase 5 的切分结论

最终切分原则如下：

- `Phase 4`: access/admin 主链路落地
- `Phase 4.5`: 收尾、管理、控制、页面补齐、约束收紧、兼容债清理
- `Phase 5`: 审计、治理、长期平台化能力

这条边界在本文件中固定，不再反复讨论。
