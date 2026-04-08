# Product Modes And Session Semantics

## 目的

这份文档用于统一 `Direct Ask / Skill Run / Skill Chat` 的产品定义，避免前端路由、后端接口和调用方心智继续混用。

## 核心对象

- `skill`
  - 执行模板
  - 决定 `provider / model / system_prompt / retrieval_config / generation_config / conversation_config / document scope`

- `session`
  - 上下文状态
  - 决定某个 skill 下的连续对话历史如何参与本次推理

- `run`
  - 一次实际执行
  - 等于：`skill template + session context + current question + current override`

## 产品模式

### 1. Direct Ask

- 接口：`POST /api/v1/chat/ask`
- 语义：文档级无状态单轮问答
- 特点：
  - 必须保留
  - 不读取 session history
  - 不作为聊天产品主入口

适用场景：

- 后台调度
- 临时问答
- 外部工具单次查询

### 2. Skill Run

- 接口：`POST /api/v1/chat/skills/{skill_id}/run`
- 语义：skill 级统一执行入口

支持三种调用形态：

1. `session_id` 为空，`auto_create_session=false`
   - 视为 skill 的无状态执行
   - 这是 skill 体系下的 one-shot API

2. `session_id` 为空，`auto_create_session=true`
   - 视为开启一个新的 skill chat session
   - 本次 run 会返回新建的 `session_id`

3. `session_id` 存在
   - 视为在既有会话中继续
   - 此时 `auto_create_session` 无效

### 3. Skill Chat

- 主产品形态
- 以 session 为基本容器
- 语义：在某个 skill 作用域下持续对话

产品原则：

- 前端聊天页不鼓励无 session 调用
- 进入 skill chat 页时，应该尽量保证：
  - 已有 `session_id` 则继续
  - 没有 `session_id` 则自动创建

## Session 管理原则

### 主推荐路径

不要求调用端必须先显式创建 session。  
主推荐方式是：

- `POST /chat/skills/{skill_id}/run`
- 传 `auto_create_session=true`

这样可以一把梭开启新会话，并在响应中拿到 `session_id`。

### 高级能力

session 管理接口继续保留：

- `POST /api/v1/chat/skills/{skill_id}/sessions`
- `GET /api/v1/chat/skills/{skill_id}/sessions`
- `GET /api/v1/chat/skills/{skill_id}/sessions/{session_id}`
- `GET /api/v1/chat/skills/{skill_id}/sessions/{session_id}/messages`

这些接口用于：

- 前端预创建空会话
- 会话列表管理
- 高级路由和会话运营能力

但不作为普通调用方的主推荐路径。

## Session 约束

- `session_id` 不存在：返回错误
- `session_id` 属于其他 tenant：返回错误
- `session_id` 属于其他 skill：返回错误
- `session_id` 存在时，`auto_create_session` 被忽略
- 禁止 session collision，禁止跨 skill 混用

## Stream 兼容策略

### 当前实现

当前后端已支持统一入口：

- `POST /api/v1/chat/skills/{skill_id}/run`
- `stream: boolean = false`

并保留兼容接口：

- `POST /api/v1/chat/skills/{skill_id}/run/stream`

### 产品收敛方向

产品上将 stream 视为 `Skill Run` 的一种执行模式，而不是独立产品模式。

统一 contract：

- `POST /api/v1/chat/skills/{skill_id}/run`
- `stream: boolean = false`

规则：

- 默认 `stream=false`
- 当 `stream=true` 时，返回 SSE
- 当 `stream=false` 时，返回普通 `ChatRunOut`

### 兼容策略

兼容策略：

- 保留 `/run/stream` 兼容旧前端
- 新前端优先按 `stream` 参数接统一入口
- 等统一入口稳定后，再考虑是否废弃 `/run/stream`

## 当前推荐产品口径

- `Direct Ask`
  - 文档级无状态问答

- `Skill Run`
  - skill 级执行入口
  - 可无状态，也可会话化
  - 可普通返回，也可流式

- `Skill Chat`
  - skill 的会话式多轮产品形态
  - 以 session 为核心

## 不应继续模糊的点

- 不要把 `skill`、`session`、`run` 混为一个概念
- 不要让聊天 UI 默认落到无 session one-shot 心智
- 不要把 stream 当成另一套产品，只应看作 run 的一种返回方式
