# Frontend Handoff: Session And Stream Alignment

## 目的

这份文档只描述前端需要配合的产品对齐点，不重复后端内部实现细节。

## 需要前端接受的产品定义

### 1. Direct Ask

- 继续视为无状态单轮
- 不要包装成聊天会话

### 2. Skill Chat 是主产品形态

- 进入 `/chat/skills/:skillId` 时，应优先走 session 语义
- 如果当前没有 `session_id`：
  - 推荐第一次提问时传 `auto_create_session=true`
  - 或前端先显式创建 session 再进入聊天页

重点：

- 聊天页不鼓励无 session 调用
- 无 session 的 skill run 只应被理解为 API one-shot，而不是产品主路径

## 当前后端支持

### Skill Run

接口：

- `POST /api/v1/chat/skills/{skill_id}/run`

新增/已支持字段：

- `session_id?: string`
- `auto_create_session?: boolean`
- `session_title?: string`
- `conversation_config`
- `retrieval_config`
- `generation_config`

语义：

- `session_id` 存在：继续既有会话
- `session_id` 为空且 `auto_create_session=true`：自动创建新会话
- `session_id` 为空且 `auto_create_session=false`：无状态 one-shot skill run

### Skill Stream

当前兼容接口：

- `POST /api/v1/chat/skills/{skill_id}/run` with `stream=true`
- `POST /api/v1/chat/skills/{skill_id}/run/stream`

产品收敛方向：

- 现在已支持统一到 `/run` + `stream=true`
- 当前仍保留 `/run/stream` 兼容

## 前端待对齐动作

### P0

- Skill Chat 页面首次发送消息时，若无 `session_id`，默认传：
  - `auto_create_session=true`
- 从返回结果中读取 `session_id`，并写回当前路由/状态
- Skill Chat 页面将“无 session”视为过渡态，而不是稳定态

### P0

- 对普通 `run` 与 `run/stream` 统一产品表达：
  - 普通模式：非流式
  - 流式模式：SSE
- 不要把 `/run/stream` 当成另一套不同产品，只是 Skill Run 的兼容入口

### P0

- 如果 `session_id` 已存在，前端不应再主动传 `auto_create_session=true`
- 即使传了，后端会忽略；但前端不应制造歧义

### P1

- UI 中明确区分：
  - Direct Ask
  - Skill Run one-shot
  - Skill Chat session

### P1

- 对 `execution_context` 做显式展示，尤其是：
  - `conversation.history_used`
  - `conversation.history_messages_used`
  - `retrieval.rewritten_query`
  - `provider`
  - `model`

## 当前不建议的前端行为

- 不要在 Skill Chat 页长期停留在“没有 session 的聊天态”
- 不要把无 session skill run 的结果展示成“这个会话记住了上下文”
- 不要继续把 stream 看成一条完全独立的产品链路
