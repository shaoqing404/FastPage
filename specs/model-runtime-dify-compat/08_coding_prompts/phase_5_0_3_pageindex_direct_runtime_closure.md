# Phase 5.0.3 — PageIndex Direct Runtime Closure

## 任务目标

把文档解析、pageindex 原生抽取、SkillChat 检索阶段的小型 LLM 调用从默认 LiteLLM 路径迁到 Direct OpenAI-compatible runtime，并把 token counting 从默认 LiteLLM token_counter 路径移除。

## 前置阅读

1. `specs/model-runtime-dify-compat/10_pageindex_direct_runtime_closure_scope.md`
2. `specs/model-runtime-dify-compat/06_migration_roadmap.md`
3. `specs/model-runtime-dify-compat/02_current_state_analysis.md`
4. `specs/model-runtime-dify-compat/08_coding_prompts/phase_5_0_1_monday_provider_runtime_delivery.md`

## 必须遵守的边界

### 允许修改

1. `pageindex/utils.py`
2. `pageindex/page_index.py`
3. `pageindex/page_index_md.py`，仅限 token counting 调用适配需要
4. `app/services/pageindex_service.py`，仅限 shared helper 调用参数传递或测试暴露需要
5. `app/services/chat_service.py`，仅限 shared helper 调用参数传递或测试暴露需要
6. `tests/phase4/` 或 `tests/phase5/` 中与本任务直接相关的测试
7. 必要文档更新

### 禁止修改

1. 不重写 Provider Center UI。
2. 不重写 SkillChat 配置页。
3. 不重写 SkillChat runtime 的 provider template / snapshot 合并逻辑。
4. 不主动改 Compliance 主链专属逻辑。
5. 不实现 model-gateway。
6. 不引入新的厂商 SDK。
7. 不删除 LiteLLM 依赖。
8. 不迁移 embedding/rerank adapter 架构。
9. 不为 embedding 增加 No auth runtime 支持。
10. 不为 rerank 增加 No auth runtime 支持。
11. 不改 DashScope native rerank helper 的鉴权语义。
12. 不改数据库 schema 或 migration。

## 实现要求

### 1. `llm_completion()` 默认 Direct

`pageindex.utils.llm_completion()` 必须：

1. 保留现有函数签名，除非为了兼容调用点必须追加可选参数。
2. `settings.enable_litellm is False` 时使用 `DirectChatAdapter.completion()`。
3. `settings.enable_litellm is True` 时使用旧 `litellm.completion()`。
4. 保留现有 retry、fatal model error、trace_hook、stats_hook、`return_finish_reason` 语义。
5. 从 `request_options` 中提取 `api_base`、`api_key`、`extra_headers` 作为 HTTP adapter 配置，不放进最终 JSON payload。
6. 没有 `request_options.api_base` 时使用系统 fallback：`settings.llm_base_url`、`settings.llm_api_key`、`settings.llm_model`。
7. 空 chat api key 时不发送 `Authorization` header。
8. Direct 请求模型只 strip `openai/` 和 `litellm/` 历史 routing hint，保留真实 namespace。

### 2. `llm_acompletion()` 默认 Direct

`pageindex.utils.llm_acompletion()` 必须：

1. 默认进入 Direct runtime。
2. 保留 `ENABLE_LITELLM=true` 回滚。
3. 不阻塞 event loop；如复用同步 helper，使用 `asyncio.to_thread()`。
4. 返回 assistant text string。

### 3. `pageindex/page_index.py` 调用点闭环

必须审计并必要时最小调整 `pageindex/page_index.py` 中所有 `llm_completion()` / `llm_acompletion()` 调用点。

要求：

1. 每个调用点默认最终进入 Direct runtime。
2. 若调用点需要运行时 endpoint 配置，沿调用链传递 `request_options`，不要在每个 prompt 函数里直接 new adapter。
3. 不改 prompt 内容。
4. 不改 TOC/页码/summary 算法。
5. 任务结果中列出已审计调用点。

### 4. App service 间接调用闭环

`app/services/pageindex_service.py` 与 `app/services/chat_service.py` 中经 `llm_completion()` 触发的 query rewrite、outline selection、JSON repair、LLM fallback rerank 等应随 shared helper 自动迁移。

如发现缺少 `api_base/api_key/extra_headers` 传递，只做最小参数传递修复。

### 5. Token counting 不再默认走 LiteLLM

`count_tokens()` / `get_page_tokens()` 必须从默认路径移除 `litellm.token_counter()`。

要求：

1. 本地 token 计数，不发 HTTP。
2. tokenizer 可用时优先用本地 tokenizer。
3. tokenizer 不可用时使用字符估算兜底。
4. 估算失败不能让文档解析任务崩溃。
5. 不要求与 LiteLLM token_counter 数值完全一致，但要保守。

## 测试要求

至少覆盖：

1. `ENABLE_LITELLM=false` 时 `llm_completion()` 不调用 `litellm.completion()`，而调用 Direct adapter。
2. `ENABLE_LITELLM=true` 时 `llm_completion()` 调用旧 LiteLLM 分支。
3. `llm_acompletion()` 默认 Direct。
4. `count_tokens()` 不调用 `litellm.token_counter()` 默认路径，并有 fallback。
5. Direct request payload 不包含 `api_base`、`api_key`、`extra_headers`。
6. 空 chat api key 不发送 Authorization。

建议运行：

```bash
DATA_DIR=./data uv run --with pytest python -m pytest \
  tests/phase4/test_direct_chat_adapter.py \
  tests/phase4/test_pageindex_llm_failfast.py \
  tests/phase5/test_endpoint_resolution.py \
  -q
```

如果新增了专门测试文件，把它加入命令。

## Docker 验收提示

本任务完成后，在 Docker full stack 中触发一次同类文档解析任务。验收重点不是完全没有 `LiteLLM` 字符串，而是同类解析阶段不再出现：

```text
LiteLLM completion() model=...
```

`app/core/llm.py` 初始化、依赖存在、`ENABLE_LITELLM=true` 回滚能力可以保留。

## 交付说明必须包含

1. 修改文件列表。
2. 已审计的 `pageindex/page_index.py` LLM 调用点列表。
3. 行为变化。
4. 测试结果。
5. Docker smoke 结果或未执行原因。
6. 未完成事项与风险。
