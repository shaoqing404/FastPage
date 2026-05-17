# Model Runtime Dify Compat — 设计文档导航

## 目标

构建 Dify-compatible model-gateway，使 pageindex-service 不再被模型厂商 SDK 污染，并且未来可以复用 Dify 官方/社区 provider 插件包的更新能力。

## 阶段路线图

```
Phase 5.0: 验收当前 endpoint 抽象
  ↓
Phase 5.0.1: Stabilize Direct OpenAI Path and Disable LiteLLM
  ↓
Phase 5.0.3: PageIndex Direct Runtime Closure
  ↓
Phase 5.0.2: Provider Center product refactor
  ↓
Phase 5.1: model-gateway MVP
  ↓
Phase 5.2: embedding/rerank adapter 化
  ↓
Phase 5.3: Dify schema compatibility
  ↓
Phase 5.4: Dify plugin package import
  ↓
Phase 5.5: runtime sandbox
  ↓
Phase 5.6: plugin-daemon / marketplace 评估
```

当前阶段：**Phase 5.0.3 coding**。Phase 5.0.1 已把 SkillChat final answer 默认迁到 `DirectChatAdapter`，但 Docker 验证发现文档解析与 pageindex 原生抽取仍通过 `pageindex.utils.llm_completion()` 触发 LiteLLM。主控已批准 Phase 5.0.3，目标是收口这些剩余 LLM 文本生成与 token counting 热路径。

## 文档目录

| 编号 | 文档 | 职责 | 状态 |
|------|------|------|------|
| 01 | `01_architecture_vision.md` | 高层架构愿景、目标、非目标、边界决策 | 📝 草案 |
| 02 | `02_current_state_analysis.md` | pageindex-service 当前模型调用架构的完整分析 | 📝 草案 |
| 03 | `03_model_gateway_design.md` | model-gateway 服务设计、API contract、组件图 | 📝 草案 |
| 04 | `04_dify_compat_layer.md` | Dify 兼容层设计 —— provider/model schema、调用协议、参数映射 | 📝 草案 |
| 05 | `05_plugin_package_format.md` | Dify 插件包格式分析、manifest/provider/model yaml 规范 | 📝 草案 |
| 06 | `06_migration_roadmap.md` | 分阶段迁移路线图，每阶段的 in/out scope、风险、验收标准 | 📝 草案 |
| 06 tasks | `06_agent_tasks/` | 待分发的子 agent 调研提示词 | 📝 可分发 |
| 07 | `07_agent_reports/` | 子 agent 调研报告（只读，原始输出） | 🔄 进行中 |
| 08 | `08_coding_prompts/` | 给 coding agent 的实现提示词 | 📝 Phase 5.0.1 已生成 |
| 09 | `09_provider_center_skillchat_runtime_product_design.md` | Provider Center / SkillChat / Runtime 的产品边界、模板继承、Embedding Profile 与后续任务拆分 | 📝 草案 |
| 10 | `10_pageindex_direct_runtime_closure_scope.md` | 文档解析/pageindex 原生抽取链路迁到 Direct runtime 的 Phase 5.0.3 审定规格 | 📝 待主控审定 |

## 关键约束

1. api-worker 不再引入新的厂商 SDK
2. 周一前保留 OpenAI-compatible 直连快路径
3. LiteLLM 可保留依赖与回滚路径，但不作为默认主调用链方向
4. model-gateway 不作为周一前强依赖
5. 不删除现有 LiteLLM 文件（除非当前任务就是迁移/替换）
6. 所有新接口必须有 contract test
7. credential 日志必须脱敏
8. 一次只做一个 Phase 的一小块

## 关联文档

- `spec/fastapi_service/phase5_maintenance_and_audit_governance/phase5_0_model_runtime_execution_prompts.md` —— Phase 5.0 实现上下文
- `spec/fastapi_service/phase5_maintenance_and_audit_governance/phase5_0_model_runtime_control_plane.md` —— 控制平面设计
