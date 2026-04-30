# Phase 4 Incremental Design

## 1. Phase 4 范围定义

### 本阶段明确要实现的内容

- 引入 `workspace_memberships`，使 Workspace 内角色与权限成为真实后端能力
- 引入 `workspace_invites`，支持按邮箱邀请尚未注册用户进入 workspace
- 在 `User` 上新增系统级能力字段：
  - `can_create_workspace`
  - `is_platform_admin`
- 在 `KnowledgeBase` 与 `ChatSkill` 上新增统一的 `visibility` 枚举：
  - `private`
  - `workspace_read`
  - `workspace_edit`
- `SkillChat` 不新增 visibility 字段，继承 `Skill.visibility`
- 将 `Workspace` 的“删除”能力收口为 `archive`
- 将 `workspace_membership` 纳入 `Principal` 和授权判定链路
- 补齐 Workspace 成员管理、Founder 转让、Invite 流、Workspace archive、visibility 修改接口
- 将 `POST /api/v1/auth/context/switch` 一并纳入本期，作为 Workspace 权限模型落地后的必要上下文切换能力

### 本阶段明确不实现的内容

- physical delete / purge of workspace
- 跨 tenant 的平台级后台管理台逻辑
- 完整的平台级 operator 控制面
- 复杂组织结构、部门、团队树
- 更细粒度的对象级 ACL
- email 投递基础设施本身
  - 本期只定义 invite 记录和接受流
- 计费、配额、审计报表等平台治理能力

### 与现有 spec / 代码的主要冲突点

- 当前 spec 的角色模型仍停留在 `tenant_membership.role = owner/admin/member`，而 Phase 4 需要明确的 workspace 级角色体系
- 当前代码没有 `workspace_memberships`，只有 `tenant_memberships`
- 当前代码没有 invite 机制
- 当前 `KnowledgeBase.status` 与 `ChatSkill.is_active` 不能表达共享级别
- 当前 `Principal` 只承载 `tenant_id / workspace_id / membership_role`，不足以表达 workspace 级角色与覆盖权限
- 当前 router/service 授权主要是“workspace 过滤 + 少量角色字段存在”，还没有形成统一能力判断

## 2. Spec 改动清单

### 需要修改的已有 spec 文件

#### [README.md](spec/fastapi_service/phase4_access_and_admin_control_plane/README.md)

建议补充章节：

- `Phase 4 Goal`
- `Scope`
- `Fixed Decisions`
- `Relationship To Phase 3.6`
- `Non-Goals`

建议说明：

- Phase 4 不是重新定义 tenant/workspace 基础模型，而是在 Phase 3 foundation 上增加 access/admin control plane

#### [tenant_and_workspace_model.md](spec/fastapi_service/phase4_access_and_admin_control_plane/tenant_and_workspace_model.md)

建议补充/修改章节：

- `Membership and role model`
  - 增加 `workspace_memberships`
  - 保留 `tenant_memberships` 但弱化其直接资源访问职责
- `Workspace model`
  - 增加 archive 字段与行为
- `Principal model`
  - 增加 `workspace_membership_role`
  - 增加 `workspace_permissions`
- `Authorization rules`
  - 改写为 tenant gate + workspace gate + visibility gate 三层
- `New APIs to add`
  - 增加 workspace member / invite / founder transfer / archive

#### [knowledge_base_and_multi_manual.md](spec/fastapi_service/phase4_access_and_admin_control_plane/knowledge_base_and_multi_manual.md)

建议补充/修改章节：

- `knowledge_bases` 资源字段
  - 新增 `visibility`
- `authorization / sharing`
  - 定义 `private / workspace_read / workspace_edit`
- `workspace member interactions`
  - guest/member/admin/founder 如何读写 KB

#### [workspace_operator_gap_audit.md](spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_operator_gap_audit.md)

建议补充/修改章节：

- 在 audit 结论后追加 `Phase 4 resolution plan`
- 标明哪些 Phase 3 gap 在 Phase 4 被正式承接

#### [phase3_frontend_closeout_report.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase3_frontend_closeout_report.md)

不建议大改正文，只需补一段 note：

- 该文档只代表 Phase 3 frontend closeout
- Phase 4 新增成员管理/邀请/visibility/归档的前端感知面由新 spec 管理

### 建议新增的 spec 文件

- `phase4_incremental_design.md`
  - 本文件，作为总设计入口
- `workspace_access_control.md`
  - 专门定义 workspace roles、capabilities、override 结构、visibility 判定链路
- `workspace_invitation_flow.md`
  - 定义 invite 生命周期、接受流程、注册衔接、幂等规则
- `workspace_admin_api.md`
  - 定义 Workspace 成员管理、Founder 转让、Archive API 合同
- `migration_plan.md`
  - 定义 `workspace_memberships`、`visibility`、`user flags` 的迁移与兼容步骤

### 已创建的 Phase 4 spec 目录

- [phase4_access_and_admin_control_plane](spec/fastapi_service/phase4_access_and_admin_control_plane)

已复制的 Phase 3 基线文件：

- [README.md](spec/fastapi_service/phase4_access_and_admin_control_plane/README.md)
- [tenant_and_workspace_model.md](spec/fastapi_service/phase4_access_and_admin_control_plane/tenant_and_workspace_model.md)
- [knowledge_base_and_multi_manual.md](spec/fastapi_service/phase4_access_and_admin_control_plane/knowledge_base_and_multi_manual.md)
- [phase3_frontend_closeout_report.md](spec/fastapi_service/phase4_access_and_admin_control_plane/phase3_frontend_closeout_report.md)
- [workspace_operator_gap_audit.md](spec/fastapi_service/phase4_access_and_admin_control_plane/workspace_operator_gap_audit.md)

## 3. 数据模型增量设计

### `User`

当前模型：

- `id`
- `tenant_id`
- `username`
- `password_hash`
- `is_active`
- `created_at`

Phase 4 新增：

- `email: String(255) | NULL initially`
- `can_create_workspace: bool = false`
- `is_platform_admin: bool = false`
- `updated_at`

建议：

- `email` 本期建议加入，因为 invite 以邮箱为主键链路，没有 email 会导致接受流程需要额外映射层
- `tenant_id` 继续保留为兼容字段，不作为长期权限真相来源

### `Workspace`

当前模型：

- `id`
- `tenant_id`
- `name`
- `slug`
- `status`
- `is_default`
- `created_by`
- `default_provider_id`
- `created_at`
- `updated_at`

Phase 4 建议新增：

- `archived_at: datetime | NULL`
- `archived_by: str | NULL`

建议约束：

- `status` 枚举化为：
  - `active`
  - `archived`
- `is_default=true` 的 workspace 不允许 archive

### `WorkspaceMembership`

新增表：

- `id`
- `workspace_id`
- `user_id`
- `role`
- `status`
- `permissions_override_json`
- `created_by`
- `created_at`
- `updated_at`

建议枚举：

- `role`:
  - `founder`
  - `admin`
  - `member`
  - `guest`
- `status`:
  - `active`
  - `disabled`
  - `removed`

建议约束：

- `UNIQUE(workspace_id, user_id)`
- founder 唯一约束：
  - 逻辑规则上要求每个 workspace 恰好一个 active founder
  - 数据库层建议增加部分唯一索引
    - `UNIQUE(workspace_id) WHERE role='founder' AND status='active'`
  - 如果当前数据库方言/迁移兼容性不便统一实现，就在应用层和测试层双重保证，并在支持的数据库上补 partial unique index

### `WorkspaceInvite`

新增表：

- `id`
- `workspace_id`
- `email`
- `role`
- `permissions_override_json`
- `status`
- `invited_by`
- `accepted_user_id`
- `expires_at`
- `accepted_at`
- `revoked_at`
- `created_at`
- `updated_at`

建议枚举：

- `status`:
  - `pending`
  - `accepted`
  - `expired`
  - `revoked`

建议约束：

- 允许同一邮箱多次历史邀请，但同一 workspace 同一邮箱同时只能有一个 `pending` invite
- 建议增加规范化邮箱字段或统一 lower-case 存储

### `KnowledgeBase`

当前模型：

- `tenant_id`
- `workspace_id`
- `name`
- `description`
- `status`
- `retrieval_profile_json`
- `created_by`

Phase 4 新增：

- `visibility: String(32) = 'private'`

建议枚举：

- `private`
- `workspace_read`
- `workspace_edit`

默认值：

- `private`

说明：

- `status` 保留，语义是“资源是否启用”
- `visibility` 新增，语义是“workspace 内共享级别”

### `ChatSkill`

当前模型：

- `tenant_id`
- `workspace_id`
- `owner_user_id`
- `knowledge_base_id`
- `provider_id`
- `is_active`

Phase 4 新增：

- `visibility: String(32) = 'private'`

建议枚举与默认值：

- 同 `KnowledgeBase.visibility`
- 默认 `private`

说明：

- `SkillChat` 继承 `ChatSkill.visibility`
- 不在 `ChatSession` / `ChatRun` 新增 visibility

### `TenantMembership` 在 Phase 4 的定位

建议：

- 保留，不迁移删除
- 定位弱化为 tenant access gate，而不是 workspace 内资源授权主体

Phase 4 后职责划分：

- `TenantMembership`
  - 决定用户是否能进入 tenant
  - 承担 tenant-level control plane 权限
- `WorkspaceMembership`
  - 决定用户是否能进入 workspace
  - 承担 workspace 内资源与管理权限

### `permissions_override` 的建议结构

建议 JSON 结构：

```json
{
  "can_manage_members": true,
  "can_manage_invites": true,
  "can_transfer_founder": false,
  "can_manage_api_keys": false,
  "can_manage_providers": false,
  "can_manage_knowledge_bases": true,
  "can_manage_skills": true,
  "can_edit_workspace_metadata": false,
  "can_archive_workspace": false
}
```

规则：

- key 缺失表示使用角色默认值
- 只允许白名单 key
- 不允许任意自由扩展字段进入运行时判定

## 4. 权限判定链路设计

### 最小侵入接入方案

保留当前模式：

- `Principal`
- `require_principal()`
- router/service 内联校验

不要一次性重构成 decorator-heavy RBAC 框架。

### `workspace_membership` 如何进入 Principal

`Principal` 建议新增：

- `tenant_membership_role`
- `workspace_membership_role`
- `workspace_membership_status`
- `workspace_permissions: dict[str, bool]`

其中：

- `tenant_membership_role` 来自 `TenantMembership.role`
- `workspace_membership_role` 来自 `WorkspaceMembership.role`
- `workspace_permissions` = `role default capabilities + permissions_override_json`

### `tenant_membership` 与 `workspace_membership` 的职责划分

#### `TenantMembership`

负责：

- 用户是否属于该 tenant
- 是否允许进入该 tenant
- tenant-level 管理动作
  - tenant 级成员管理
  - tenant 级 provider / tenant default provider
  - tenant 级 API key（若后续保留）

#### `WorkspaceMembership`

负责：

- 用户是否属于该 workspace
- workspace 内角色
- workspace 成员/邀请管理
- workspace 资源的读写管理
- visibility 语义中的“workspace 可见/可编辑”判定

### 默认角色能力矩阵

建议默认矩阵：

#### `founder`

- can_view_workspace = true
- can_edit_workspace_metadata = true
- can_manage_members = true
- can_manage_invites = true
- can_transfer_founder = true
- can_archive_workspace = true
- can_manage_api_keys = true
- can_manage_providers = true
- can_manage_knowledge_bases = true
- can_manage_skills = true

#### `admin`

- can_view_workspace = true
- can_edit_workspace_metadata = true
- can_manage_members = true
- can_manage_invites = true
- can_transfer_founder = false
- can_archive_workspace = false
- can_manage_api_keys = true
- can_manage_providers = true
- can_manage_knowledge_bases = true
- can_manage_skills = true

#### `member`

- can_view_workspace = true
- can_edit_workspace_metadata = false
- can_manage_members = false
- can_manage_invites = false
- can_transfer_founder = false
- can_archive_workspace = false
- can_manage_api_keys = true
- can_manage_providers = false
- can_manage_knowledge_bases = true
- can_manage_skills = true

#### `guest`

- can_view_workspace = true
- 其余默认写能力全部 false

### `permissions_override` 如何覆盖默认角色能力

规则建议：

1. 先取角色默认矩阵
2. 再按 `permissions_override_json` 覆盖
3. 对 founder 的关键能力做硬保护：
   - `can_transfer_founder`
   - `can_archive_workspace`
   - 不允许通过 override 给非 founder 提升

也就是说：

- override 可用于降权
- 部分能力可允许小范围升权
- founder-only 动作不能靠 override 升权获得

### 哪些动作必须 founder 才能执行

- transfer founder
- archive workspace
- 修改 founder 本身
- 移除当前 founder 身份

### 哪些动作 admin 可以执行

- list members
- update non-founder memberships
- create/revoke invites
- update workspace metadata
- 管理 KB / Skill / provider / workspace-scoped API key

### `visibility` 校验建议放在哪一层

建议放在 service 层，而不是 router 层。

原因：

- KB / Skill / SkillChat 的访问路径不止一个
- service 层更容易统一复用
- router 只负责拿到 `Principal` 和资源 id

推荐做法：

- 新增 `access_control_service.py` 或 `workspace_access_service.py`
- 提供：
  - `can_read_knowledge_base(principal, kb)`
  - `can_edit_knowledge_base(principal, kb)`
  - `can_read_skill(principal, skill)`
  - `can_edit_skill(principal, skill)`

## 5. API / 服务层改动建议

### Workspace 成员管理

新增：

- `GET /api/v1/workspaces/{workspace_id}/members`
- `POST /api/v1/workspaces/{workspace_id}/members`
- `PATCH /api/v1/workspaces/{workspace_id}/members/{membership_id}`
- `DELETE /api/v1/workspaces/{workspace_id}/members/{membership_id}`
  - 语义建议为 `status=removed`，不是物理删除

服务建议新增：

- `workspace_membership_service.py`

### Founder 转让

新增：

- `POST /api/v1/workspaces/{workspace_id}/founder-transfer`

payload 建议：

- `target_user_id`

规则：

- 仅 active founder 可执行
- 目标用户必须已有 active workspace membership
- 转让应在单事务内完成：
  - 原 founder -> admin 或 member
  - 目标成员 -> founder

### Invite 发起 / 接受 / 撤销

新增：

- `GET /api/v1/workspaces/{workspace_id}/invites`
- `POST /api/v1/workspaces/{workspace_id}/invites`
- `POST /api/v1/workspace-invites/{invite_id}/accept`
- `POST /api/v1/workspaces/{workspace_id}/invites/{invite_id}/revoke`

建议接受流：

- 如果当前登录用户 email 与 invite email 匹配，则接受
- 若邮箱尚未注册，需要先注册/绑定后再接受
- 如果系统当前没有注册流程，本期可允许由现有登录用户接受匹配邮箱 invite，未注册用户接受动作先定义 contract

服务建议新增：

- `workspace_invite_service.py`

### Workspace archive

新增：

- `POST /api/v1/workspaces/{workspace_id}/archive`

规则：

- 仅 founder 可执行
- default workspace 不可 archive
- archive 后：
  - 禁止作为 active workspace 切入
  - 成员默认不可继续操作该 workspace
  - 已有资源保留

### KnowledgeBase / Skill visibility 更新

建议修改现有接口：

- `PATCH /api/v1/workspaces/{workspace_id}/knowledge-bases/{kb_id}`
- `PATCH /api/v1/skills/{skill_id}`

新增字段：

- `visibility`

服务层：

- `knowledge_base_service.py`
- `skill_service.py`

### Workspace context switch

建议纳入本期。

原因：

- 一旦 `workspace_membership` 生效，没有正式 switch API，前端无法进入多 workspace 场景
- 这项在 Phase 3 spec 已提过，但未实现，Phase 4 应正式承接

新增：

- `POST /api/v1/auth/context/switch`

payload 建议：

- `workspace_id`

返回建议：

- 新 token
- current tenant/workspace context
- active tenant membership
- active workspace membership

## 6. 数据迁移与兼容方案

### 如何初始化 `workspace_memberships`

迁移建议：

1. 对每个现有 workspace
2. 找到该 workspace 所属 tenant 的 active `tenant_memberships`
3. 为这些成员创建默认 `workspace_memberships`

默认映射建议：

- tenant `owner` -> workspace `founder` 仅限 default workspace
- tenant `admin` -> workspace `admin`
- tenant `member` -> workspace `member`

对于非 default workspace：

- 如果当前系统里还没有明确 workspace 成员边界，建议先将现有 tenant 成员都 backfill 为 workspace `member`
- 但 founder 仍然唯一，优先给 workspace.created_by；若缺失则给 tenant owner

### 如何处理已有 `tenant_membership`

保留。

Phase 4 不做迁移删除，也不改其历史意义。

建议：

- 继续作为 tenant access gate
- 新资源授权逻辑不再只看 `tenant_membership.role`
- workspace 内动作优先看 `workspace_membership`

### 已有 KnowledgeBase / Skill 没有 visibility 时如何迁移

建议 migration 默认值：

- `KnowledgeBase.visibility = 'private'`
- `ChatSkill.visibility = 'private'`

理由：

- 最安全
- 不会意外放大现有资源可见范围
- 符合当前实际行为接近“同 workspace 内创建即用，但无正式共享语义”

### 现有 token / principal / context 逻辑如何兼容过渡

兼容策略：

- 旧 token 没有 workspace membership 信息时，仍可先通过 `tenant_id + workspace_id` 解析
- `require_principal()` 在 Phase 4 中增加：
  - 解析 tenant membership
  - 解析 workspace membership
  - 若 workspace membership 缺失或非 active，则拒绝

JWT 建议新增字段：

- `workspace_membership_role`

但不要求一次性把所有权限展开进 token。

更稳妥方式：

- token 存最小上下文
- 每次请求仍查 DB 解析 membership 与 override

### 哪些步骤必须通过 migration 执行

- `users` 新增字段：
  - `email`
  - `can_create_workspace`
  - `is_platform_admin`
  - `updated_at`
- `workspaces` 新增字段：
  - `archived_at`
  - `archived_by`
- 新表：
  - `workspace_memberships`
  - `workspace_invites`
- `knowledge_bases.visibility`
- `chat_skills.visibility`
- founder 唯一约束索引
- `workspace_invites` 的状态/邮箱索引

### 哪些可以通过应用层兼容

- 旧 token 到新 principal 的过渡解析
- `permissions_override_json` 的默认空对象
- archive 后资源访问的拒绝逻辑
- visibility 默认行为

## 7. 推荐实施顺序

### 1. spec

- 先更新 Phase 4 总设计
- 再单独细化：
  - access control
  - invitation flow
  - admin API
  - migration plan

### 2. migration

- 新增 `users` 字段
- 新增 `workspaces` archive 字段
- 新增 `workspace_memberships`
- 新增 `workspace_invites`
- 新增 `visibility`
- 执行 backfill
- 添加 founder 唯一约束

### 3. model

- 更新：
  - `User`
  - `Workspace`
  - `KnowledgeBase`
  - `ChatSkill`
- 新增：
  - `WorkspaceMembership`
  - `WorkspaceInvite`

### 4. auth/principal

- 扩展 `Principal`
- 扩展 `require_principal()`
- 增加 workspace membership resolution
- 增加 capability resolution helper
- 落地 `auth/context/switch`

### 5. service/router

优先顺序建议：

1. workspace membership service/router
2. founder transfer
3. invite service/router
4. workspace archive
5. KB visibility
6. Skill visibility
7. context switch
8. 将关键资源接入 visibility 校验

### 6. tests

至少覆盖：

- founder 唯一约束
- founder transfer 事务一致性
- guest/admin/member/founder 默认能力矩阵
- override 降权和有限升权
- invite pending/accepted/revoked/expired
- 未注册邮箱 invite 可存在
- archive 后 workspace 不可切入
- KB/Skill visibility 读写差异
- context switch + workspace membership 联动

## 8. 需要我确认的剩余开放问题

以下问题无法仅靠现有 spec、代码和已冻结 8 项推出：

1. `WorkspaceMembership` 的 backfill 映射规则
   - 对于非 default workspace，是否默认把 tenant 内所有 active 成员都 backfill 进去？
   - 还是只 backfill `created_by`、资源拥有者、tenant owner/admin？

2. founder 转让后的原 founder 默认降级成什么角色
   - `admin`
   - 还是 `member`

3. invite 接受的注册衔接 contract
   - 当前系统没有正式注册接口
   - Phase 4 是否需要补一个最小注册/激活接口，还是只先定义“现有用户接受 invite”

4. `email` 在 `User` 上是否要求唯一
   - 我建议唯一
   - 但这需要确认是否接受未来一个邮箱对应多个本地账号的不支持

5. admin 是否允许管理其他 admin
   - 例如修改 admin 的 role/status
   - 还是只能 founder 管理 admin

6. `workspace_edit` visibility 是否允许 `guest` 通过资源 visibility 直接获得写能力
   - 我建议不允许
   - visibility 只决定资源可共享范围，不突破 membership 角色上限

7. archived workspace 下的 membership / invite 是否立即失效
   - 我建议 invite 立即不可再接受
   - membership 保留历史但不允许 active use

## 9. 前端/管理台影响面

### 需要新增的页面或功能入口

- Workspace 成员管理入口
- Invite 管理入口
- Founder 转让入口
- Workspace archive 入口
- Workspace 创建入口
  - 对 `User.can_create_workspace` 感知
- KB visibility 选择器
- Skill visibility 选择器

### 现有页面需要因权限逻辑调整而改动

- 登录后 workspace 上下文不再只是静态 localStorage，需要支持正式 switch
- Knowledge Bases 页面
  - 需要展示/编辑 visibility
  - 根据角色能力隐藏编辑入口
- Skills 页面
  - 需要展示/编辑 visibility
  - 根据角色能力限制编辑/发布
- Control Plane / Providers 页面
  - 需要按 workspace membership capability 控制是否可见、可编辑
- API Key 管理页
  - 需要按 capability 控制创建/撤销能力
- Skill Chat / Runs / Sessions 页面
  - 需要按 skill visibility + workspace membership 过滤读写入口

### 是否需要单独的管理台路由或权限隔离

建议需要，但不必做独立产品壳。

建议：

- 在现有 workspace console 中增加 admin 区域
- 路由层面可以新增：
  - `/workspace/settings`
  - `/workspace/members`
  - `/workspace/invites`

不建议当前阶段单独拆一套平台管理台，除非后续要启用 `is_platform_admin` 的完整后台逻辑。
