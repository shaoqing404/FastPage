# Phase 4.5 Closeout, Management, and Control

## 1. 定位

`Phase 4.5` 是 `Phase 4 Access and Admin Control Plane` 的收尾阶段。

它不是重新定义 `Phase 4`，也不是提前进入 `Phase 5`。

本阶段的职责只有三类：

- 收尾：补齐 Phase 4 已冻结但尚未彻底闭环的后端和产品缺口
- 管理：把 Phase 4 选择性后置的管理页面和配套 API 明确纳入可执行范围
- 控制：补齐平台级最小控制面，使 `workspace` / `user` / `context` 从“可用”变成“可运营”

在当前调整后的执行计划中，`Phase 4.5` 还额外吸收两类此前容易被后置的工作：

- invite onboarding / password lifecycle 的最小产品闭环
- Knowledge Base / Documents 管理页面的信息架构收口

边界上：

- `Phase 4` 解决的是 workspace access/admin 主干能力
- `Phase 4.5` 解决的是这些能力的收口、管理面、控制面、兼容债清理
- `Phase 5` 才进入审计、治理、长期运营、配额/策略/报表等长期平台能力

## 2. 输入前提

本文件基于 `Phase 4` 的**实际代码状态**，不是只基于原始 spec。

主要参考：

- [phase4_incremental_design.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase4_incremental_design.md)
- [workspace_access_control.md](spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_access_control.md)
- [workspace_invitation_flow.md](spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_invitation_flow.md)
- [workspace_admin_api.md](spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_admin_api.md)
- [migration_plan.md](spec/fastapi_service/phase4_access_and_admin_control_plane/migration_plan.md)

以及实际代码：

- [auth.py](app/core/auth.py)
- [principal.py](app/core/principal.py)
- [workspace_access_service.py](app/services/workspace_access_service.py)
- [workspace_admin_service.py](app/services/workspace_admin_service.py)
- [workspace_invite_service.py](app/services/workspace_invite_service.py)
- [workspace_scope_service.py](app/services/workspace_scope_service.py)

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
- invite 入口到可进入 workspace 的 onboarding 面
- KB / Documents 管理面的职责边界收口

### 4.3 控制目标

建立一个**轻量但真实可用**的平台控制面：

- 能看
- 能管
- 能收口关键操作

但不扩张成完整治理平台。

这里的“控制”还包括：

- 用户被邀请后，能够通过明确的登录 / claim / 改密路径进入 workspace
- 平台管理员能够完成最小密码重置与账户恢复动作
- 用户能在 KB / Documents 两个页面中理解资源管理边界，而不是依赖混合式临时页面

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

#### C. invite onboarding 与 account entry 闭环

`Phase 4` 冻结了 invite 的 email matching 与 accept 规则，但未完成产品入口闭环。

本阶段正式纳入：

- invite preview contract
- invite 链接在未登录状态下的明确入口分流
  - 已有账号登录后 accept
  - invite-bound claim / first-entry flow
- invite claim 成功后的 token/context handoff
- 已存在账号但未登录时的稳定回跳

边界说明：

- 这不是开放式 public signup
- 这是 invite-bound onboarding
- invite UUID 只作为该 invite 的 claim 凭证，不扩张成通用注册体系
- `Phase 4.5` 的正式 closeout 主链仍以 platform-admin provisioning 为主验证链

### 5.3 兼容债清理

本阶段要继续清理仍依赖 `User.tenant_id` 作为行为主导的内部路径。

至少包括：

- [chat_service.py](app/services/chat_service.py#L398)
- [chat_service.py](app/services/chat_service.py#L418)
- [chat_service.py](app/services/chat_service.py#L556)

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
- 平台管理员触发 password reset
- 对需要首登改密的用户状态提供最小可见性

本阶段不做：

- 完整审批链
- SSO / SCIM
- 外部身份治理

说明：

- 如果 invite claim / 首登改密在本阶段实现，则平台用户管理必须提供与之配套的最小密码运营动作
- 这仍属于 operational control，不属于长期 IAM 平台

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
- Knowledge Base 列表页与详情页拆分
- KB 详情页中的文档管理入口
- Documents 页面重新聚焦为用户个人文档管理入口
- KB 与 Documents 两个页面间的“上传 / 关联 / 分享到 KB”边界澄清

#### C. Invite 侧页面

- invite accept page
- invite accept 成功后的 token/context 替换流程
- invite preview state
- 未登录用户的 claim / login 分流
- 已登录但邮箱不匹配时的稳定错误反馈
- 首登改密页与受控跳转

#### D. 平台管理侧页面

- platform users page
- platform user detail/edit page
- platform workspaces page
- platform workspace detail page

说明：

- 这些页面是 `Phase 4` 选择性后置的管理页面
- `Phase 4.5` 要把它们正式纳入范围
- 但页面实现仍应尽量复用已有 layout、导航、auth client、主题变量
- KB / Documents 页面重构在本阶段被视为“管理面收口”，不是新的知识产品线扩张
- invite claim / password change / reset-password UI 在本阶段被视为“账户进入闭环”，不是新的身份平台建设

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
7. 默认模型按当前运行面约定验证
   - 当前 DashScope 兼容运行面默认模型为 `openai/qwen-plus`
8. 测试用户上传项目目录内 PDF
9. parse / index / build 成功
10. 创建 skill 并绑定 KB
11. 完成 query / skill chat
12. 验证 tenant / workspace / capability API 隔离

说明：

- `Phase 4.5` 不要求开放 public signup
- 测试用户由 platform admin provision 即可
- closeout 测试优先使用项目目录内 PDF，而不是外部不稳定样本
- 如果 invite claim / password lifecycle 在本阶段落地，应单独追加产品验证，但不得替代 provisioning-based closeout 主链

### 5.9 当前 closeout 审计状态（2026-04-17）

截至 `2026-04-17`，`Phase 4.5` 的正式 closeout 状态更新为 `Conditional GO`。

原因不是主链仍未打通，而是主链已经在真实运行面上完成重跑，但仍保留少量应记录到 `Phase 4.7` 的 hardening 条件。

当前状态拆分如下：

- 已完成基于真实 `.env` 运行面的 closeout 复验
  - 复验口径为远程 `MySQL + MinIO + Redis`
  - 当前结论为 `Conditional GO`
  - 已通过的真实链路包括：
    - bootstrap admin 登录
    - `POST /api/v1/platform/users`
    - 新用户登录
    - workspace 创建 / context 自动切换 / workspace list / context switch
    - invite create + accept
    - founder transfer / archive 抽样
    - KB -> provider -> repo-local PDF -> parse/index/build -> skill -> query / skill chat
    - platform users / workspaces / tenants 管理面抽样
    - 非 platform admin 与 API key 访问 `/api/v1/platform/*` 的 `403`
    - 跨 workspace 资源访问负向验证
- 已完成一次针对 Claude 中间实现批的代码审计
  - 审计对象为基于中间 implementation plan 的实现批，而不是正式 `Phase 4.5` 结项
  - 该批次的范围归属应并入 `Phase 4.5 frontend closeout`
  - 该批次覆盖：
    - invite preview / claim / accept handoff
    - change-password / platform reset-password 最小闭环
    - KB selector / KB detail 页面拆分
    - Documents 页面重聚焦为个人文档入口
    - `uploaded_via_kb_id` 文档来源链路
  - 该批次在修复 `Documents` owner scope 后，代码级结论可记为 `GO for this batch`
  - 该结论只表示“可并入 4.5 收口证据”，不等于 `Phase 4.5` 总体 closeout 已转为 `GO`
- 已识别的主阻塞中，以下两项已完成代码级修复，并已在真实运行面完成复验
  - `platform user provisioning`
    - `POST /api/v1/platform/users` 对应的 `create_platform_user()` 已通过先写入 `User` 再附加 membership 的方式修复 FK 顺序问题
    - 配套 contract test 已确认 user / tenant membership / default workspace membership 成功落库
    - 真实 MySQL 运行面已确认平台管理员可完成测试用户创建与后续登录
  - `query / skill chat`
    - chat event publish 边界已改为 datetime-safe
    - terminal wait 轮询已改为显式刷新事务视图，避免 MySQL 下的假 `504`
    - 相关 regression tests 已通过
    - 真实 Redis worker 运行面已确认 `POST /api/v1/chat/ask` 与 `POST /api/v1/chat/skills/{skill_id}/run` 成功
- 对上述两项修复的当前判定是：
  - 代码审计通过
  - 真实运行面复验通过
  - 可以计入 `Phase 4.5` 正式 closeout 证据
- 对 Claude 中间实现批的当前判定是：
  - 应按 `Phase 4.5` 中间批次归档，而不是重标为 `Phase 4.6`
  - invite onboarding / password lifecycle 的最小产品闭环已具备可审计实现
  - KB / Documents 页面 IA 收口已具备可审计实现
  - 但其正式有效性仍需在 `Phase 4.7` 的真实运行面链路中补手动 / 端到端验证
- migration metadata hygiene 已不再是当前阻塞项
  - `uv run alembic heads` 已收敛到单 head `20260416_0010`
  - `uv run alembic current` 已与该 head 一致
- 仍需记录并滚入 `Phase 4.7` 的事项包括：
  - 将当前偏手工的 runtime closeout 流程标准化为 runbook / skill / checklist
  - 为验证过程中产生的临时用户、临时 API key、密码重置等工件定义 cleanup 规则
  - 在后续 hardening 中补齐更标准化的 cross-tenant 负向验证证据

约束说明：

- SQLite 或纯单测结果只能作为辅助证据
- `Phase 4.5` 的正式 closeout 主结论必须以真实 `MySQL + MinIO + Redis` 链路为准
- 目前之所以仍记录为 `Conditional GO` 而不是无条件 `GO`，是因为：
  - 产品面上尚未把 cross-tenant 负向验证标准化为一个稳定、低人工成本的 operator 流程
  - 运行面 closeout 过程仍需 `Phase 4.7` 做 operationalization

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
- 通用 public signup / registration 平台
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
- `POST /api/v1/platform/users/{user_id}/reset-password`

### 7.3 平台 workspace 管理

- `GET /api/v1/platform/workspaces`
- `GET /api/v1/platform/workspaces/{workspace_id}`
- `POST /api/v1/platform/workspaces/{workspace_id}/archive`
- `POST /api/v1/platform/workspaces/{workspace_id}/unarchive`
- `POST /api/v1/platform/workspaces/{workspace_id}/founder-transfer`

### 7.4 Tenant / directory 只读视图

- `GET /api/v1/platform/tenants`
- `GET /api/v1/platform/tenants/{tenant_id}`

### 7.5 Invite onboarding / password lifecycle

- `GET /api/v1/workspace-invites/{invite_id}/preview`
- `POST /api/v1/workspace-invites/{invite_id}/claim`
- `POST /api/v1/auth/change-password`

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
- 当前补充状态：
  - platform user provisioning 的 MySQL FK 顺序修复已完成代码审计
  - 仍需真实运行面 API 复验后才能视为 closeout 通过

### Batch 4.5-E: frontend closeout

- workspace switcher
- workspace admin pages
- invite accept page
- invite preview / claim / change-password / reset-password UI
- KB selector / KB detail page restructuring
- Documents page refocus
- visibility UI
- platform admin pages
- 当前补充状态：
  - 已完成一次针对 Claude 基于中间 implementation plan 产出批次的代码审计
  - 该批次不是正式 `Phase 4.5` closeout，而是 4.5 范围内的中间实现批
  - 该批次在修复 `Documents` owner scope 后，代码级判定可记为 `GO for this batch`
  - 后续应将其作为 `Phase 4.5 frontend closeout` 的已审计输入，进入 `Phase 4.7` 运行面验证

### Batch 4.5-F: environment reset and closeout chain

- 环境清理脚本或 runbook
- 干净初始化流程
- API 全链路验证
- 形成 4.5 closeout 结果
- 当前补充状态：
  - A/B 阻塞项已完成代码级复审
  - 本 batch 的首要 gate 变为真实 `MySQL + MinIO + Redis` 复验与 migration metadata 对齐

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
- invite 链接在未登录状态下有清晰的 login / claim 分流
- 首登改密与平台重置密码形成最小闭环
- 用户可以设置 KB / Skill visibility
- KB 与 Documents 页面职责边界已清晰，不再依赖混合式管理页面
- 允许创建 workspace 的用户可以完成自助创建
- 平台 admin 可以通过后台页面管理用户和 workspace

### 10.3 范围纪律

- 未把审计与长期治理混入 `Phase 4.5`
- 未把 purge / billing / quota / policy engine 混入 `Phase 4.5`
- 管理页面与后端 contract 保持一一对应，而不是做无后端支撑的空壳页面

### 10.4 closeout 验证

- 开发/验证环境可被安全清理到空初始化状态
- 可从干净状态完成 migration 与 bootstrap
- 可完成 platform admin -> test user -> workspace -> KB -> provider -> PDF -> query / skill chat 的完整链路
- API 层 tenant / workspace / capability 测试覆盖关键授权边界
- 本阶段 closeout 结果可作为 `Phase 4.7` 测试标准的输入

补充 gate：

- 若某项阻塞已完成代码修复但尚未通过真实运行面复验，`Phase 4.5` 仍视为未 close
- `Phase 4.7` 只能继承已经在真实运行面复验通过的 `Phase 4.5` 能力，不继承“仅单测通过”的假定结论

## 11. 与 Phase 5 的切分结论

最终切分原则如下：

- `Phase 4`: access/admin 主链路落地
- `Phase 4.5`: 收尾、管理、控制、页面补齐、约束收紧、兼容债清理
- `Phase 5`: 审计、治理、长期平台化能力

这条边界在本文件中固定，不再反复讨论。

## 12. Phase 5 前阶段重叠梳理

在进入 `Phase 5` 前，`Phase 4.5 / 4.6 / 4.7` 会共享同一批实体、API 和页面，但职责不同。

### 12.1 `Phase 4.5` 与 `Phase 4.6`

重叠程度：`中等`

共享对象：

- platform users / tenants / workspaces
- membership 信息
- invite / workspace / KB / Documents 的可见性边界

职责切分：

- `Phase 4.5` 负责：
  - operational control
  - onboarding / password / 页面收口
  - 最小管理动作与产品闭环
- `Phase 4.6` 负责：
  - relationship truth
  - explainability
  - access portrait / directory read model

判断规则：

- 主要回答“怎么进入、怎么管理、怎么收口”的工作归 `4.5`
- 主要回答“为什么允许、为什么拒绝、当前关系真相是什么”的工作归 `4.6`

### 12.2 `Phase 4.5` 与 `Phase 4.7`

重叠程度：`低`

共享点只有一个：

- `4.7` 要验证 `4.5` 已落地的能力

但边界很硬：

- `4.5` 做实现与收口
- `4.7` 做 reset / rebuild / integration / end-to-end hardening

因此：

- `4.7` 可以继承 `4.5` 的 invite/password/KB/Documents 收口结果
- `4.7` 不应再次设计这些产品面

### 12.3 `Phase 4.6` 与 `Phase 4.7`

重叠程度：`低`

共享点：

- `4.7` 会验证 `4.6` 的 directory / access portrait 输出是否稳定可复验

边界：

- `4.6` 负责定义和落地 relationship-truth contract
- `4.7` 负责把这些 contract 放入 release gate

### 12.4 `Phase 4.x` 与 `Phase 5`

重叠程度：`概念上接近，职责上应保持低重叠`

容易混淆的词：

- auditability
- operator visibility
- control plane
- platform management

这些在 `Phase 4.x` 中都仍然属于“为进入治理做准备”，不等于已经进入 `Phase 5`。

`Phase 5` 才正式吸收：

- audit center / audit platform
- governance workflow
- quota / billing / policy
- 长期运营分析与平台化治理

结论：

- 这次 Claude 中间实现批与 `Phase 5` 的直接重叠很低
- 它应被视为 `Phase 4.5 frontend/product closure` 的一部分，而不是提前进入治理阶段
