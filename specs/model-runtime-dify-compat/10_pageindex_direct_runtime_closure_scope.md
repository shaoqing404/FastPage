# 10 — PageIndex Direct Runtime Closure Scope

**状态**：主控已批准，进入 Phase 5.0.3 coding，基于 2026-05-17 23:16-23:30 运行日志复盘
**目标读者**：用户、主控架构 AI、Phase 5.0.3 coding agent、Docker 验收 agent
**前置阅读**：`02_current_state_analysis.md`、`06_migration_roadmap.md`、`09_provider_center_skillchat_runtime_product_design.md`、`08_coding_prompts/phase_5_0_1_monday_provider_runtime_delivery.md`

## 文档职责

定义 Phase 5.0.3 的收口边界：把文档解析、pageindex 原生抽取、SkillChat 检索阶段的小型 LLM 调用从默认 LiteLLM 路径迁到 Direct OpenAI-compatible runtime。

本文档只处理 LLM 文本生成与 token 计数热路径，不扩大到 Provider Center 产品重构、SkillChat 配置页重写、embedding/rerank adapter 化或 Compliance 主链重构。

## 背景

Docker 验证时，`api` 容器日志持续出现：

```text
LiteLLM completion() model= qwen3.6-plus; provider = openai
```

这不是 Docker build 日志，而是 worker 运行时日志。触发来源主要是文档解析和 pageindex 原生抽取链路仍调用 `pageindex.utils.llm_completion()` / `llm_acompletion()`，这些函数当前默认调用 `litellm.completion()` / `litellm.acompletion()`。

Phase 5.0.1 已将 SkillChat final answer stream 默认迁到 `DirectChatAdapter`，但没有覆盖 pageindex 库层的非流式/异步 LLM 调用。因此文档解析会在 TOC 检测、TOC 转换、完整性检查、继续生成、页码修复、summary/description 等阶段持续触发 LiteLLM。

用户确认：当前链路应当收口，不再赌客户内网 OpenAI-compatible endpoint 能被 LiteLLM 正确代理。

## 钉死边界

### In Scope

1. `pageindex.utils.llm_completion()` 默认走 `DirectChatAdapter.completion()`。
2. `pageindex.utils.llm_acompletion()` 默认走 Direct runtime，可通过线程桥接同步 adapter 或提供等价 async direct helper。
3. `ENABLE_LITELLM=true` 保留旧 LiteLLM 回滚分支。
4. `pageindex/page_index.py` 中所有 `llm_completion()` / `llm_acompletion()` 调用点必须被审计，确保默认行为最终进入 Direct runtime。
5. 如调用点缺少运行时连接信息，允许对 `pageindex/page_index.py` 做最小签名传递改动，把 `request_options` / runtime config 传到 shared helper。
6. `app/services/pageindex_service.py` 中通过 `llm_completion()` 发起的 query rewrite、outline selection、JSON repair、LLM fallback rerank、legacy non-stream answer，必须默认进入 Direct runtime。
7. `app/services/chat_service.py` 中 retrieval query rewrite 仍经 `llm_completion()`，因此必须随 shared helper 自动迁到 Direct runtime。
8. `count_tokens()` 和 `get_page_tokens()` 不再默认依赖 `litellm.token_counter()`；改为当前 runtime 可接受的本地 token 估算路径，例如 tiktoken 本地编码优先、字符长度估算兜底。
9. 保留现有 prompt、JSON repair、retry、trace_hook、stats_hook、`return_finish_reason` 语义。
10. Direct HTTP 请求边界仍只 strip 历史 routing hint：
    - `openai/foo` -> `foo`
    - `litellm/foo` -> `foo`
    - `zai/glm-4.7-flash` 等真实 namespace 原样保留。
11. 默认不强塞 `stream_options.include_usage`；usage 缺失时 metrics/observation 按缺失处理。

### Out of Scope

1. 不重写 Provider Center UI。
2. 不重写 SkillChat 配置页。
3. 不重写 SkillChat runtime 的 provider template / snapshot 合并逻辑。
4. 不改 Compliance 主链专属逻辑。
5. 不实现 model-gateway。
6. 不引入新的厂商 SDK。
7. 不删除 LiteLLM 依赖。
8. 不迁移 embedding/rerank adapter 架构。
9. 不为 embedding 增加 No auth runtime 支持；当前 `OpenAICompatibleEmbeddingClient` 继续要求 api_key 非空。
10. 不为 rerank 增加 No auth runtime 支持。
11. 不改 DashScope native rerank helper 的鉴权语义；内网 rerank 不走该 helper。
12. 不改变数据库 schema。

## 需求优先级

### P0.1 Shared LLM Helper Direct Default

`pageindex.utils.llm_completion()` 是本阶段最关键的边界。它必须成为非流式 Direct OpenAI-compatible LLM 调用入口。

要求：

1. 默认读取 `settings.enable_litellm`。
2. `False` 时构造 `DirectChatAdapter` 并调用 `completion()`。
3. `True` 时保持旧 `litellm.completion()` 行为。
4. 支持 `request_options` 中的：
   - `api_base`
   - `api_key`
   - `extra_headers`
   - `temperature`
   - `max_tokens`
   - `max_completion_tokens`
   - 其他 DirectChatAdapter 可透传的 OpenAI-compatible generation options
5. 没有 `request_options.api_base` 时，使用系统 fallback：
   - `settings.llm_base_url`
   - `settings.llm_api_key`
   - `settings.llm_model` 或调用参数 `model`
6. 不把 `api_base`、`api_key`、`extra_headers` 放进最终 JSON payload。
7. 空 api key 时 chat direct runtime 不发送 `Authorization` header。

### P0.2 Async LLM Helper Direct Default

`pageindex.utils.llm_acompletion()` 必须和同步 helper 语义一致。

要求：

1. 默认进入 Direct runtime。
2. 保留 `ENABLE_LITELLM=true` 回滚。
3. 如果使用 `asyncio.to_thread()` 包装同步 helper，必须避免阻塞 event loop。
4. 保持返回值仍为 assistant text string。

### P0.3 PageIndex Parse Call Site Closure

`pageindex/page_index.py` 不是绕过对象。所有 LLM 调用点都必须被纳入 Direct 默认行为。

要求：

1. 审计所有 `llm_completion()` / `llm_acompletion()` 调用。
2. 确认 TOC detector、TOC extractor、TOC transformer、TOC index extractor、incorrect TOC fixer、node summary、doc description 等阶段不再默认触发 LiteLLM。
3. 若现有调用只传 `model`，且运行时需要 endpoint 信息，允许最小化增加 `request_options` 参数并沿调用链传递。
4. 不改 prompt 内容，不改解析算法，不做顺手重构。

### P0.4 App Service Indirect Call Closure

以下链路通过 shared helper 自动迁移，不应各自手写 DirectChatAdapter：

1. `app/services/pageindex_service.py` 的 JSON repair。
2. `app/services/pageindex_service.py` 的 outline selection。
3. `app/services/pageindex_service.py` 的 LLM fallback rerank。
4. `app/services/pageindex_service.py` 的 query rewrite。
5. `app/services/pageindex_service.py` 的 legacy non-stream final answer helper。
6. `app/services/chat_service.py` 的 retrieval query rewrite。

### P0.5 Token Counting LiteLLM Removal

`count_tokens()` / `get_page_tokens()` 当前默认依赖 `litellm.token_counter()`。本阶段需要从默认链路移除该依赖。

要求：

1. token 计数必须是本地行为，不发 HTTP。
2. 优先使用本地可用 tokenizer，例如 tiktoken 缓存或已有依赖。
3. tokenizer 不可用时使用稳定字符估算兜底。
4. 估算失败不能让文档解析任务崩溃。
5. 不要求与 LiteLLM token_counter 完全一致，但要保持上下文预算保守。

### P1 Tests and Evidence

必须提供测试证据，而不只依赖 Docker 肉眼日志。

要求：

1. 增加或更新 unit tests，断言 `ENABLE_LITELLM=false` 时 `llm_completion()` 不调用 `litellm.completion()`。
2. 增加或更新 unit tests，断言 `ENABLE_LITELLM=true` 时保留旧回滚。
3. 增加或更新 async helper 测试。
4. 增加 token counting fallback 测试。
5. Docker smoke 观察：文档解析同类任务不再出现 `LiteLLM completion()` 日志。

## 非目标解释

### 为什么不改 embedding No auth

用户已重新收窄边界：如果当前 `OpenAICompatibleEmbeddingClient` 强制要求 api_key 非空，则本阶段接受该限制，不补充 embedding No auth。Provider Center 的 No auth 产品语义后续可以单独再审，但本阶段不让它拖大 P0。

### 为什么不改 rerank No auth

内网 rerank 不走 DashScope native rerank helper。本阶段不需要为 DashScope native rerank helper 增加 No auth，也不改变 generic rerank 已有行为。

### 为什么不改 Compliance 主链

Compliance 已确认存在模型 runtime 耦合，但不进入当前 P0 主实现。若 shared helper 迁移后 Compliance 自然使用 Direct runtime，应通过回归测试确认不破坏现有 provider 解析；但不做 Compliance 专属 runtime 重构。

## 验收标准

1. `ENABLE_LITELLM=false` 时，文档解析/pageindex 原生抽取链路不再默认调用 `litellm.completion()` 或 `litellm.acompletion()`。
2. `ENABLE_LITELLM=true` 时，旧 LiteLLM completion 路径可回滚。
3. `pageindex/page_index.py` 中每个 LLM 调用点已审计并记录在实现结果中。
4. `count_tokens()` / `get_page_tokens()` 默认不调用 `litellm.token_counter()`。
5. SkillChat final answer 现有 Direct streaming 行为不回退。
6. embedding/rerank runtime 行为不因本阶段发生鉴权语义变化。
7. Compliance 主链没有被主动重写。
8. 无新增数据库 migration。
9. 测试清单通过，Docker smoke 有日志证据。

## 回滚方案

1. 设置 `ENABLE_LITELLM=true` 可恢复 LLM helper 的旧 LiteLLM completion 路径。
2. token counting 若新 tokenizer 路径异常，应自动落到字符估算，不需要回滚配置。
3. 若 Direct runtime 在文档解析中遇到客户 endpoint 不兼容，优先通过 provider/base_url/model 配置修复；临时可打开 LiteLLM 回滚，但默认仍保持 Direct。

## 主控审定问题

请主控确认：

1. 是否批准 Phase 5.0.3 作为 Phase 5.0.1 之后的 runtime closure hotfix。
2. 是否同意本阶段改 `pageindex/page_index.py` 的最小调用链签名传递。
3. 是否同意 token counting 从 LiteLLM 迁到本地 tokenizer/字符估算，不要求数值完全等价。
4. 是否确认 embedding/rerank No auth 不进入本阶段。
5. 是否确认 Compliance 专属主链仍不进入本阶段。
