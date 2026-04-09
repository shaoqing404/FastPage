# Phase 2: Chat App 能力扩展（非向量，后端优先）

## 目标

在保持 PageIndex 非向量检索体系不变的前提下，将当前 `skills` 能力升级为更完整的 Chat App 级后端能力，并完成前端承接。  
本阶段优先后端扩展，前端在后端稳定后跟进。

说明：你提到的 `openai-compelation` 此处统一按 **OpenAI-compatible Chat Completions** 规范实现。

## 核心原则

- 不引入向量检索，不引入向量库，不破坏现有 PageIndex 结构化检索主路径。
- 强化租户隔离，所有业务对象与鉴权均严格 tenant-scope。
- API 目录与包结构按可扩展方式重整，避免后续路由平铺扩散。
- 保持向后兼容：旧 `skills` 与现有接口在过渡期可继续运行。

## Phase Plan

## Phase 1：后端基础扩展（租户隔离 + API Key）

### 1.1 租户隔离强化

- 全面检查并统一 `tenant_id` 约束：documents、skills、runs、jobs、metrics、provider 配置。
- 鉴权依赖层输出统一 principal（session user 或 api-key principal）。

### 1.2 API Key 能力（租户级）

- 新增租户级 API Key 数据模型：
  - `id`, `tenant_id`, `name`, `key_prefix`, `key_hash`, `status`, `created_by`, `last_used_at`, `revoked_at`, `created_at`
- 安全规则：
  - 明文 key 仅创建时返回一次
  - 数据库存 hash，不可逆
  - 吊销后立即失效

### 1.3 API 与目录结构

- 新增接口：
  - `POST /api/v1/auth/apikeys`
  - `GET /api/v1/auth/apikeys`
  - `DELETE /api/v1/auth/apikeys/{key_id}`
- 鉴权支持：
  - `Authorization: Bearer <token>`
  - `X-API-Key: <key>`
- 路由与包整理建议：
  - `app/api/routers/v1/auth/session.py`
  - `app/api/routers/v1/auth/apikeys.py`
  - `app/core/auth/session.py`
  - `app/core/auth/apikey.py`
  - `app/core/auth/principal.py`

## Phase 2：后端模型接入扩展（租户自定义大模型）

### 2.1 Provider Profile 能力

- 新增租户级模型供应商配置（provider profile）：
  - 支持 `dashscope`（阿里云百炼）
  - 支持 `deepseek`
  - 支持 `openai_compatible`
- 配置项：
  - `provider_type`, `name`, `base_url`, `api_key_secret_ref`, `default_model`, `supported_models`, `extra_headers`, `enabled`

### 2.2 Provider 管理接口

- `POST /api/v1/model-providers`
- `GET /api/v1/model-providers`
- `PATCH /api/v1/model-providers/{provider_id}`
- `DELETE /api/v1/model-providers/{provider_id}`
- `POST /api/v1/model-providers/{provider_id}/probe-models`

当前后端已补最小可用多模型 contract：

- `supported_models: string[]`
- `managed_by_system: boolean`
- 若未显式传入，后端会自动回填为 `[default_model]`
- 当前不做自动探测，仅支持“provider 默认模型 + 多模型显式维护”
- 系统默认 provider 会以数据库记录形式暴露，并通过 `managed_by_system=true` 标识
- 后端会拒绝编辑或删除该系统托管 provider

另外已补最小可用探测接口：

- `POST /api/v1/model-providers/{provider_id}/probe-models`
- 优先请求真实 `/models`
- 探测成功后将结果写回 `supported_models`
- 探测失败返回明确 `502`，不静默伪造模型列表

### 2.3 执行链路接入

- skill/chat 执行时按优先级解析 provider：
  1. skill 绑定 provider
  2. 租户默认 provider
  3. 系统默认 provider
- 拆分请求配置：
  - `retrieval_config`（检索阶段）
  - `generation_config`（回答阶段）

## Phase 3：后端技能执行协议升级（skills id + 引用标识）

### 3.1 通过 skills id 指定聊天能力

- 保持 `/chat/skills/{skill_id}/run` 为主入口。
- 将 skill 视为 Chat App profile，逐步兼容升级。

### 3.2 非向量检索配置增强

- 在现有结构化检索基础上增加可配置项（不引入向量）：
  - `top_k`
  - `selection_mode`（`outline_llm` / `lexical_fallback`）
  - `max_context_pages`
  - `max_context_tokens`

### 3.3 回答引用特殊标识

- 模型回答完成后追加标准尾部标识：

```text
---
[CITATIONS_JSON_BEGIN]
{...json...}
[CITATIONS_JSON_END]
```

- 同时返回结构化字段：
  - `answer_text`
  - `answer_with_marker`
  - `citations[]`（`node_id`, `title`, `page_start`, `page_end`, `snippet_id`）
- 过渡期保留 `selected_sections` 兼容旧前端。

## Phase 4：多轮与多 session 机制（最小可用）

- 已实现最小可用 session：
  - `chat_sessions`
  - `chat_messages`
  - `chat_runs.session_id`
- 已补 skill-scoped session 后端接口：
  - `POST /api/v1/chat/skills/{skill_id}/sessions`
  - `GET /api/v1/chat/skills/{skill_id}/sessions`
  - `GET /api/v1/chat/skills/{skill_id}/sessions/{session_id}`
  - `GET /api/v1/chat/skills/{skill_id}/sessions/{session_id}/messages`
- skill chat 已升级为“真多轮”最小实现，仅作用于：
  - `POST /api/v1/chat/skills/{skill_id}/run`
- 执行语义收敛为三层：
  - `skill = 执行模板`
  - `session = 上下文状态`
  - `run = 一次实际执行`
- 新增共享层 `conversation_config`：
  - `query_rewrite_with_history`
  - `include_history`
  - `include_assistant_messages`
  - `history_turn_limit`
  - `history_token_budget`
- `conversation_config` 采用父子覆盖：
  - `skill.conversation_config` 为父模板
  - `skill run payload.conversation_config` 为本次 override
- history 参与策略：
  - retrieval：先基于最近历史做 query rewrite，失败则回退原 question
  - generation：直接注入裁剪后的 conversation context
- `direct ask` 仍保持单轮，不读取 session history
- run 返回结构化 `execution_context`，供前端直接展示有效执行语义：
  - `provider`
  - `model`
  - `conversation`
  - `retrieval`
  - `generation`

## Phase 5：前端扩展（后端完成后实施）

### 5.1 管理能力

- API Key 管理页：创建、查看、吊销、一次性复制。
- Provider 管理页：百炼/DeepSeek/OpenAI-compatible 配置与连通性测试。

### 5.2 Skills/Chat 承接

- Skills 页面增强：
  - provider 绑定
  - 检索参数配置（非向量）
  - 生成参数配置
- Chat 页面增强：
  - 展示 `answer_text`
  - 解析并展示 `citations`
  - 支持展开/隐藏尾部 JSON 引用标识
  - 以 provider-aware 方式重做 model 选择和执行上下文展示

前端问题收敛与整改方案见：

- [frontend_phase2_improvement_plan.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/frontend_phase2_improvement_plan.md)
- [frontend_rebuild_handoff.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/frontend_rebuild_handoff.md)
- [frontend_phase2_session_and_stream_handoff.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/frontend_phase2_session_and_stream_handoff.md)
- [skill_chat_stream_contract.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/skill_chat_stream_contract.md)
- [product_modes_and_session_semantics.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/product_modes_and_session_semantics.md)

## 验收标准

- Bearer 与 API Key 均可访问受保护接口；跨租户访问被拒绝。
- API Key 明文只在创建时可见，吊销后即失效。
- 三类 provider 均可完成一次 skill 问答闭环。
- 回答尾部引用标识可稳定解析，且 `citations` 与节点页码一致。
- 旧接口与旧 skills 在过渡期可正常运行。
- skill-first 聊天页面不需要再靠 `skill_id + session_id` 的前端近似过滤模拟 session 语义。
- skill chat 的 session history 必须真实进入推理链路，而不是仅用于历史归档。

## 非目标（本期明确不做）

- 向量检索、向量库、hybrid 向量召回。
- `direct ask` 的多轮对话能力。
- 更复杂的会话管理，例如摘要压缩、长期记忆、跨 session 迁移。
