# 06 — 分阶段迁移路线图

**状态**：草案，已加入周一前 hotfix phase
**目标读者**：用户、主控架构 AI、后续 coding agent
**前置阅读**：`01_architecture_vision.md` 到 `05_plugin_package_format.md`

## 文档职责

定义从当前状态到最终目标的分阶段迁移计划。每个阶段都需要明确 in scope、out of scope、前置依赖、验收标准、回滚方案和风险。

## 总体顺序

```text
Phase 5.0:   验收当前 endpoint 抽象
Phase 5.0.1: Stabilize Direct OpenAI Path and Disable LiteLLM
Phase 5.0.3: PageIndex Direct Runtime Closure
Phase 5.0.2: Provider Center product refactor
Phase 5.1:   model-gateway MVP
Phase 5.2:   embedding/rerank adapter 化
Phase 5.3:   Dify schema compatibility
Phase 5.4:   Dify plugin package import
Phase 5.5:   runtime sandbox
Phase 5.6:   plugin-daemon / marketplace 评估
```

## Phase 5.0 — 验收当前 endpoint 抽象

### In Scope

1. 确认 `model_provider_endpoints` 已支持 `capability` 与 `adapter`。
2. 确认当前 capability × adapter dispatch 是否可用。
3. 明确 `GatewayAdapter` 未来插入点。
4. 不再新增厂商 SDK 到 `api-worker`。

### Out of Scope

1. 不实现 model-gateway。
2. 不删除 LiteLLM。
3. 不迁移 embedding/rerank。

### 前置依赖

1. Phase 5.0 migration 已可运行。
2. provider runtime endpoint probe 逻辑可审计。

### 验收标准

1. `model_provider_endpoints` 可表达 chat/embedding/rerank endpoint。
2. `probe-runtime` 能按 capability 运行。
3. 已定位 chat/embedding/rerank 当前执行路径。

### 回滚方案

保留旧 provider config 解析路径，endpoint 表异常时回退 legacy capabilities 或 system env。

### 风险

当前 chat 主路径仍可能绕开 endpoint adapter dispatch，直接走 LiteLLM。

## Phase 5.0.1 — Monday Provider Runtime Delivery

### 目标

周一前保留 `api-worker` 的 OpenAI-compatible direct path，从主调用链禁用 LiteLLM，不新增任何厂商 SDK，不引入 model-gateway 作为强依赖，并保证前端可配置、可验证、可运行的租户/工作区 provider 完整路径。

2026-05-16 用户确认的 P0 业务场景：客户内网提供按 capability 分离的 OpenAI-compatible endpoint，例如 chat `/v1/chat/completions`、embedding `/v1/embeddings`、rerank `/rerank`。当前 LiteLLM 模式访问不到这类白名单内网算力，周一交付必须让前端 provider 配置与后端实际运行链路闭环。

产品判断：模型 provider / endpoint 是 workspace 可共用资源。周一交付优先让 Provider Hub 支持工作区内可管理、可验证、可设为默认、可被 SkillChat 使用的资源闭环；Compliance 等其它业务入口不作为 P0 主验收页面，但不得被本次改动破坏。

### In Scope

1. 审计 LiteLLM import、初始化、调用点。
2. 审计 `DirectChatAdapter` 调用链。
3. 让 chat final answer 默认走 `DirectChatAdapter`，并优先消费 `model_provider_endpoints(capability="chat")`。
4. 让 embedding/rerank 运行链路能消费 provider endpoint 表，确保 `chat_service.py` 调用 resolver 时传入 `db/tenant_id/workspace_id`。
5. 前端 Provider Hub 支持创建/编辑 per-capability endpoints：
   - chat: `openai_chat`
   - embedding: `openai_embedding`
   - rerank: `generic_rerank`
6. 前端支持 draft runtime probe，保存前即可验证 chat/embedding/rerank endpoint。
7. 如有必要，增加 feature flag：
   - `ENABLE_LITELLM=false`
   - `ENABLE_MODEL_GATEWAY=false`
8. 补充 smoke test / probe test。
9. 保留 LiteLLM 依赖和旧路径作为临时回滚能力，但默认配置关闭。

### Out of Scope

1. 不删除所有 LiteLLM 文件。
2. 不实现 model-gateway。
3. 不接 Dify plugin-daemon。
4. 不解析 `.difypkg`。
5. 不引入新的厂商 SDK。
6. 不重构整个前端控制台，只做 provider endpoint 配置与验证闭环。
7. 不做 batch chat 专门通道；若普通 chat endpoint 能覆盖，batch chat 延后。
8. 不把 Compliance run 作为周一 P0 主验收入口；只保证共享 provider 解析不被破坏。

### 前置依赖

1. `agent_07_litellm_direct_openai_audit` 报告返回。
2. 明确 `DirectChatAdapter` 是否能覆盖当前 streaming response 处理需求。
3. 明确现有测试中哪些 patch `litellm.completion`，避免误改大量测试。

### 验收标准

1. `api-worker` 可以正常启动。
2. 前端 Provider Hub 可以配置 chat / embedding / rerank 三类 endpoint。
3. 前端可以对草稿和已保存 provider 执行 runtime probe，并看到每个 capability 的健康状态。
4. OpenAI-compatible chat completion 可用，默认不走 LiteLLM。
5. embedding endpoint 可被 probe 验证，并在开启 provider embedding mode 的运行链路中被解析。
6. rerank endpoint 可被 probe 验证，并在 provider rerank mode 的运行链路中被解析。
7. 没有新增厂商 SDK 依赖。
8. 有明确回滚方式。
9. 因当前开发机器无法访问客户内网 endpoint，本地验收以 mock/unit/integration probe path 为准；真实客户内网 endpoint smoke 由内网环境执行并回填结果。

### 回滚方案

如果 `DirectChatAdapter` 路径异常，可以通过 feature flag 临时恢复旧 LiteLLM chat 路径。但默认配置仍然保持 LiteLLM 关闭。embedding/rerank 回滚到现有 direct clients / legacy system config。

### 风险

1. 当前 `chat_service.py` streaming 处理依赖 LiteLLM chunk object 形态，直连 adapter 返回 dict chunk 后需要极小兼容层。
2. `pageindex/utils.py` 的非流式/异步 LiteLLM 调用可能仍被 LLM fallback rerank 或库层路径使用，周一前不应贸然全删。
3. `default_llm_model()` 仍包含为 LiteLLM 服务的 `openai/` 前缀逻辑，需要审计是否影响直连 endpoint。
4. 测试中大量 patch `litellm`，最小实现应避免引发测试面爆炸。
5. Compliance 复用 shared provider resolver，但 endpoint lookup 没闭环，且 final answer 仍走 `pageindex.utils.llm_completion()`。周一不主动改 Compliance，但 shared resolver 改动需要跑基本回归，避免破坏其现有 provider 解析。

## Phase 5.0.3 — PageIndex Direct Runtime Closure

### 目标

收口 Phase 5.0.1 留下的 runtime 缺口：文档解析、pageindex 原生抽取、SkillChat 检索阶段的小型 LLM 调用不再默认走 LiteLLM，而是默认进入 Direct OpenAI-compatible runtime。

本阶段以 `10_pageindex_direct_runtime_closure_scope.md` 为审定规格入口。

主控已批准本阶段作为 runtime closure hotfix 推进；实现边界仍限定在 shared LLM helper、pageindex 原生调用和 token counting 收口。

### In Scope

1. `pageindex.utils.llm_completion()` 默认改为 `DirectChatAdapter.completion()`，保留 `ENABLE_LITELLM=true` 回滚。
2. `pageindex.utils.llm_acompletion()` 默认改为 Direct runtime，保留 `ENABLE_LITELLM=true` 回滚。
3. 审计并必要时最小修改 `pageindex/page_index.py` 中所有 `llm_completion()` / `llm_acompletion()` 调用点，确保每个文档解析 LLM 阶段默认进入 Direct runtime。
4. `app/services/pageindex_service.py` 和 `app/services/chat_service.py` 中经 shared helper 触发的 query rewrite、JSON repair、outline selection、LLM fallback rerank 等同步迁移到 Direct 默认路径。
5. `count_tokens()` / `get_page_tokens()` 从默认链路移除 `litellm.token_counter()`，改成本地 tokenizer 优先、字符估算兜底。
6. 保留 Direct 请求边界的历史 routing hint strip 策略：只 strip `openai/` 和 `litellm/`，真实 namespace 保留。
7. 补测试和 Docker smoke 证据，证明同类文档解析任务不再出现 `LiteLLM completion()`。

### Out of Scope

1. 不重写 Provider Center UI。
2. 不重写 SkillChat 配置页。
3. 不重写 SkillChat runtime 的 provider template / snapshot 合并逻辑。
4. 不主动改 Compliance 主链专属逻辑。
5. 不实现 model-gateway。
6. 不引入新的厂商 SDK。
7. 不删除 LiteLLM 依赖。
8. 不迁移 embedding/rerank adapter 架构。
9. 不为 embedding 增加 No auth runtime 支持；当前 `OpenAICompatibleEmbeddingClient` 继续要求 api_key 非空。
10. 不为 rerank 增加 No auth runtime 支持。
11. 不改 DashScope native rerank helper 的鉴权语义；内网 rerank 不走该 helper。
12. 不改变数据库 schema。

### 前置依赖

1. Phase 5.0.1 的 `DirectChatAdapter` 已可用于 non-stream completion。
2. Docker 验证已确认剩余 `LiteLLM completion()` 日志来自 worker 文档解析/pageindex 原生 LLM 调用。
3. 用户已确认 embedding/rerank No auth 需求本阶段关闭。

### 验收标准

1. `ENABLE_LITELLM=false` 时，文档解析/pageindex 原生抽取链路不再默认调用 `litellm.completion()` 或 `litellm.acompletion()`。
2. `ENABLE_LITELLM=true` 时，旧 LiteLLM completion 路径可回滚。
3. `pageindex/page_index.py` 中每个 LLM 调用点已审计并在实现结果中列出。
4. `count_tokens()` / `get_page_tokens()` 默认不调用 `litellm.token_counter()`。
5. SkillChat final answer 现有 Direct streaming 行为不回退。
6. embedding/rerank runtime 行为不因本阶段发生鉴权语义变化。
7. Compliance 主链没有被主动重写。
8. 无新增数据库 migration。
9. 单元测试通过，Docker smoke 有日志证据。

### 回滚方案

1. 设置 `ENABLE_LITELLM=true` 临时恢复旧 LiteLLM completion 路径。
2. token counting 新路径异常时自动落到字符估算。
3. 若 Direct runtime 在客户 endpoint 中遇到兼容问题，优先修 provider/base_url/model 配置；必要时临时打开 LiteLLM 回滚。

### 风险

1. `pageindex/page_index.py` 调用层级较深，若只改 shared helper 而不审计调用点，可能遗漏 runtime option 传递。
2. token counting 数值可能和 LiteLLM token_counter 不完全一致，需要保持保守预算。
3. Compliance 通过 shared helper 可能自然进入 Direct runtime，因此需要跑基本回归，但不做 Compliance 专属重构。

## Phase 5.0.2 — Provider Center Product Refactor

### 目标

把当前 `/providers` 大杂烩页面替换为层次型 Provider Center。Provider Center 是租户/工作区级模型能力模板中心，不是 SkillChat 的具体运行配置页。

本阶段以 `09_provider_center_skillchat_runtime_product_design.md` 为产品规格入口。

### In Scope

1. `/providers` 改为四卡入口：
   - API Keys
   - LLM Providers
   - Embedding Providers
   - Rerank Providers
2. 新增能力二级页：
   - `/providers/api-keys`
   - `/providers/llm`
   - `/providers/embedding`
   - `/providers/rerank`
3. 每个 provider 能力页用表格承载复杂度，用 modal 或 side panel 创建/编辑。
4. LLM / embedding / rerank 按能力拆分管理，避免把三能力 endpoint 挤在同一个 provider editor。
5. LLM/chat 支持 `No auth` / `API key` 两种 auth mode；不做 `Custom headers` auth mode。embedding/rerank No auth runtime 支持已关闭，不进入当前阶段。
6. 支持普通模式 / 开发者选项。高级参数默认隐藏，但必须有默认值。
7. 支持模型列表探测：能探测则 dropdown 选择，不能探测则使用 Provider Center 中保存的模型名。
8. 引入 Provider-owned live fields 与 Skill-owned snapshot fields 的产品边界说明，但不在本阶段重写 SkillChat。
9. Embedding Provider 页面需要表达 Embedding Profile / vector space contract 的最小概念：model key、dimensions、context window、distance metric、normalization。

### Out of Scope

1. 不重写 SkillChat 配置页。
2. 不改 SkillChat runtime 合并逻辑。
3. 不改 runtime observation。
4. 不改 Compliance 主链。
5. 不实现 model-gateway。
6. 不接 Dify plugin-daemon 或 Dify auth/header 复杂形态。

### 验收标准

1. `/providers` 首页不再展示复杂编辑表单，只展示四张入口卡和摘要。
2. API key 管理与 provider 管理分离。
3. LLM provider 可在表格中创建、编辑、删除、测试、设默认、共享。
4. Embedding provider 可配置 dimensions / context window，并提示 ES 维度风险。
5. Rerank provider 可配置默认 `top_n=512`。
6. LLM provider 默认 `temperature=0.2`、`context_window_tokens=131072`，不把 `max_tokens=131072` 作为 OpenAI 请求参数默认值。
7. LLM/chat `No auth` endpoint 能保存和 probe，不要求 API key；embedding/rerank 仍按当前 runtime 鉴权语义处理。
8. 页面布局在真实 provider 数量增多时仍保持可扫描、可比较、可操作。

### 风险

1. 当前后端 schema 偏向 `model_provider` + `model_provider_endpoints`，产品视角改为能力模板中心后，需要 coding agent 谨慎复用现有字段，避免一次性引入不必要 migration。
2. Embedding Profile 是新产品概念，若本阶段只做 UI，需要明确哪些字段先落在 endpoint `config_json`，哪些等待后续 migration。
3. SkillChat 页面尚未重写前，Provider Center 的能力模板与现有 SkillChat 消费形态会短暂不完全匹配，需要在 UI 文案中避免暗示已完成 SkillChat runtime 适配。

## Phase 5.1 — model-gateway MVP

### In Scope

1. 支持 `POST /v1/chat/completions`。
2. 支持 OpenAI-compatible endpoint。
3. 支持统一错误、日志脱敏、streaming、usage。
4. 新增 `GatewayAdapter`，但不强制替代 `DirectOpenAIAdapter`。

### Out of Scope

1. 不运行 Dify 插件。
2. 不解析 `.difypkg`。
3. 不把 gateway 设为 OpenAI-compatible 唯一路径。

### 前置依赖

1. Phase 5.0.1 稳定。
2. gateway API contract 已确认。
3. credential 日志脱敏规则已确认。

### 验收标准

1. gateway 可通过 contract test。
2. `GatewayAdapter` 可在 feature flag 下调用。
3. streaming 与 usage 行为可观测。

### 回滚方案

关闭 `ENABLE_MODEL_GATEWAY`，继续使用 `DirectOpenAIAdapter`。

### 风险

gateway 过早接管 OpenAI-compatible chat 会扩大周一前风险，因此必须 feature flag 控制。

## Phase 5.2 — embedding/rerank adapter 化

### In Scope

1. 迁移 urllib embedding。
2. 迁移 `dashscope_rerank` hardcode。
3. 统一 `/v1/embeddings` 和 `/v1/rerank`。
4. 把 Compliance 的 embedding/rerank resolver 调用补齐到共享 runtime boundary，使其能消费 `model_provider_endpoints`。

### Out of Scope

1. 不运行第三方插件。
2. 不删除 legacy fallback。

### 前置依赖

1. gateway MVP 可用。
2. embedding/rerank contract tests 可用。
3. Compliance runtime coupling audit 已消化为 `ResolvedRuntimeEndpoint` 设计。

### 验收标准

1. embedding/rerank 有统一 adapter contract。
2. `dashscope_rerank` 不再散落在业务路径中。
3. legacy path 可回滚。

### 回滚方案

按 capability 切回现有 `OpenAICompatibleEmbeddingClient` 或 `GenericRerankAdapter`。

### 风险

embedding/rerank 直接影响检索质量和排序结果，需要保留灰度与对照测试。

## Phase 5.3 — Dify schema compatibility

### In Scope

1. 支持 Dify-shaped provider/model schema。
2. 支持 validate provider/model credentials。
3. 支持 `parameter_rules` 校验。

### Out of Scope

1. 不运行 Dify 插件代码。
2. 不做 Marketplace。
3. 不做 plugin hot reload。

### 前置依赖

1. 第二批 Dify official provider 插件包结构核查完成。
2. Dify schema 字段映射已确认。

### 验收标准

1. provider/model schema 可被 gateway 读取和返回。
2. 参数校验失败有稳定错误码。
3. validate contract 有测试。

### 回滚方案

关闭 Dify-shaped schema 输入，只保留本地 provider schema。

### 风险

Dify 字段可能随版本变化，必须记录 schema version 与 minimum Dify version。

## Phase 5.4 — Dify plugin package import

### In Scope

1. 支持读取 `.difypkg` 或插件目录。
2. 解析 `manifest.yaml`、provider yaml、model yaml、`pyproject.toml`、`uv.lock`。
3. 生成 schema 快照。
4. 不运行插件代码。

### Out of Scope

1. 不执行 `main.py`。
2. 不 import 插件 Python 代码。
3. 不安装第三方依赖。

### 前置依赖

1. `.difypkg` 解包格式核查完成。
2. PackageImporter 字段需求确认。

### 验收标准

1. importer 可校验包结构。
2. importer 可生成 provider/model schema 快照。
3. importer 记录 package hash、dependency hash、imported_at、active/inactive status。

### 回滚方案

禁用 imported package provider，只使用手写 schema。

### 风险

真实 `.difypkg` 是否为 zip、是否有签名或 hash 规则，需要本地样本验证。

## Phase 5.5 — runtime sandbox

### In Scope

1. 支持受控运行第三方插件。
2. 默认容器隔离。
3. 网络白名单。
4. 文件系统隔离。
5. secret 短生命周期注入。
6. 超时和资源限制。

### Out of Scope

1. 不默认信任用户上传插件。
2. 不把 venv 当作安全边界。

### 前置依赖

1. security sandbox 方案报告完成。
2. threat model 完成。

### 验收标准

1. 插件运行有资源限制。
2. 网络访问可控。
3. secret 不落盘、不进普通日志。
4. 异常插件可被终止。

### 回滚方案

关闭 runtime execution，仅保留 schema import。

### 风险

第三方代码执行是高风险功能，venv 只隔离依赖，不隔离权限、网络和文件系统。

## Phase 5.6 — plugin-daemon / marketplace 评估

### In Scope

1. 评估是否把 Dify plugin-daemon 作为 remote runtime backend。
2. 评估 marketplace / private registry。
3. 评估运维、鉴权、DB、存储、升级与回滚成本。

### Out of Scope

1. 不把 plugin-daemon 作为早期硬依赖。
2. 不默认接入公开 Marketplace。

### 前置依赖

1. plugin-daemon 最小独立运行核查完成。
2. runtime sandbox 已形成自己的安全边界。

### 验收标准

1. 明确直接复用 plugin-daemon、remote backend、自研 lightweight host 三种路线的成本。
2. 明确 marketplace/private registry 的信任模型。

### 回滚方案

继续使用自研 gateway + schema importer，不接 plugin-daemon。

### 风险

plugin-daemon 可能带来额外 DB、存储、鉴权、进程生命周期和安全边界复杂度。
