# Phase 2 前端重构交接文档

## 目的

这份文档面向主 session / 审查者，说明本轮前端重构已经完成的内容、实现边界、关键入口、验证结果，以及下一轮若继续推进应优先检查或补强的部分。

本轮遵循的方向是：

- 不新起前端工程
- 保留现有 `React + Router + React Query + 现有后端 API`
- 重建前端骨架、设计系统和关键页面交互
- 从“深色 SaaS 模板”切换到“浅银白 Apple Pro Apps 风格专业工作台”

## 本轮已完成

### 1. 整体骨架与信息架构

已完成：

- 一级导航改为顶部悬浮导航
- 登录后默认页改为 `Overview`
- 新的真实模块结构：
  - `Overview`
  - `Documents`
  - `Skills`
  - `Chat`
  - `Control Plane`
  - `Activity`
- 原 `Metrics` 路由保留兼容，但跳转到 `Activity`

关键文件：

- [/Users/shaoqing/workspace/PageIndex/frontend/src/app/App.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/app/App.tsx)
- [/Users/shaoqing/workspace/PageIndex/frontend/src/components/layout/MainLayout.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/components/layout/MainLayout.tsx)

### 2. 设计系统与视觉风格

已完成：

- 全局主题改为浅银白 / 雾面玻璃 / 冷蓝点缀
- 移除旧的深色霓虹 + 网格背景科技感
- 建立统一工作台组件：
  - `GlassPanel`
  - `SectionToolbar`
  - `StatusBadge`
  - `EmptyState`
  - `KeyMetric`
  - `Field`
  - `ExpertDrawer`
  - `CopyOnceModal`
  - `InlineAlert`

关键文件：

- [/Users/shaoqing/workspace/PageIndex/frontend/src/styles/globals.css](/Users/shaoqing/workspace/PageIndex/frontend/src/styles/globals.css)
- [/Users/shaoqing/workspace/PageIndex/frontend/src/components/ui/workbench.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/components/ui/workbench.tsx)

### 3. Overview / Activity 新工作台

已完成：

- 新增 `Overview` 页面，承接“运营总览 + 最近工作”
- 新增 `Activity` 页面，整合 `runs / jobs / metrics`
- 不伪装成真实“系统日志后台”，而是基于当前后端真实能力组织活动与诊断

关键文件：

- [/Users/shaoqing/workspace/PageIndex/frontend/src/pages/OverviewPage.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/pages/OverviewPage.tsx)
- [/Users/shaoqing/workspace/PageIndex/frontend/src/pages/ActivityPage.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/pages/ActivityPage.tsx)
- [/Users/shaoqing/workspace/PageIndex/frontend/src/pages/MetricsPage.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/pages/MetricsPage.tsx)

### 4. Documents 页面重构

已完成：

- 文档库列表与检视器双区布局
- 顶部上传入口
- 解析中的 active jobs 展示
- 版本历史抽屉
- 原始 structure 抽屉
- 重解析、删除等动作迁入专业工作台样式

关键文件：

- [/Users/shaoqing/workspace/PageIndex/frontend/src/pages/DocumentsPage.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/pages/DocumentsPage.tsx)

### 5. Skills 页面重构

已完成：

- 去除 `Skills` 对静态 `MODEL_OPTIONS` 的主依赖
- 改为 provider-aware model 编辑逻辑
- provider 变化时，model 可按 provider `default_model` 预填
- retrieval / generation 常用项改成表单：
  - `top_k`
  - `selection_mode`
  - `max_context_pages`
  - `max_context_tokens`
  - `temperature`
- JSON 仅保留在 `ExpertDrawer`

关键文件：

- [/Users/shaoqing/workspace/PageIndex/frontend/src/pages/SkillsPage.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/pages/SkillsPage.tsx)

注意：

- 本轮没有新增后端 `supported_models`
- 因此这里仍是“provider 默认模型 + 手填覆盖”的最小正确实现

### 6. Chat 页面重构

已完成：

- 聊天区 / 上下文区 / 结果检视区三栏工作台
- `Resolved Execution Context` 明确展示：
  - mode
  - provider
  - model
  - session
  - target document
- direct ask 与 skill run 都进入 provider-aware 解析
- skill 绑定 provider 时，前端明确提示 request override 会被后端忽略
- 失败时：
  - 显示后端错误
  - 保留原问题
  - 提供 `Retry`
  - 展示 provider/model 执行上下文
- citations 与 retrieved sections 展示增强
- `answer_with_marker` 放入可展开区域，而不是默认压在主回答里

关键文件：

- [/Users/shaoqing/workspace/PageIndex/frontend/src/pages/ChatPage.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/pages/ChatPage.tsx)

### 7. Control Plane 页面重构

已完成：

- API key 创建后改为一次性复制模态
- 提供 `Copy key` 按钮与 copied 状态
- provider 编辑改成专业表单
- `extra_headers` 移入 Expert 抽屉
- 新增 `System Default Execution` 信息卡
- 将 provider 解析顺序明确展示给用户

关键文件：

- [/Users/shaoqing/workspace/PageIndex/frontend/src/pages/ControlPlanePage.tsx](/Users/shaoqing/workspace/PageIndex/frontend/src/pages/ControlPlanePage.tsx)

### 8. 类型与工具层补充

已完成：

- 新增通用工具方法：
  - className 合并
  - 日期格式化
  - page range 格式化
  - provider 解析
  - axios 错误转用户可读文本
- 将前端类型中的 `any` 清理为 `unknown` 或更明确结构

关键文件：

- [/Users/shaoqing/workspace/PageIndex/frontend/src/lib/utils.ts](/Users/shaoqing/workspace/PageIndex/frontend/src/lib/utils.ts)
- [/Users/shaoqing/workspace/PageIndex/frontend/src/types/index.ts](/Users/shaoqing/workspace/PageIndex/frontend/src/types/index.ts)
- [/Users/shaoqing/workspace/PageIndex/frontend/src/features/auth/api.ts](/Users/shaoqing/workspace/PageIndex/frontend/src/features/auth/api.ts)
- [/Users/shaoqing/workspace/PageIndex/frontend/src/features/chat/api.ts](/Users/shaoqing/workspace/PageIndex/frontend/src/features/chat/api.ts)
- [/Users/shaoqing/workspace/PageIndex/frontend/src/features/documents/api.ts](/Users/shaoqing/workspace/PageIndex/frontend/src/features/documents/api.ts)

## 与原计划的对应关系

### 已覆盖的计划点

- 顶部悬浮主导航
- `Overview` 默认首页
- Apple Pro Apps 倾向的浅银白玻璃工作台
- 页面主骨架重建
- `Skills` 的 provider-aware model 选择
- `Chat` 的 resolved execution context
- 聊天错误显式展示与 retry
- API key 一次性复制交互
- `Control Plane` 中的 system default execution 信息表达
- `Activity` 取代旧的“炫技 metrics 页面”

### 仍属于后续增强的点

- provider 多模型列表
- provider 自动探测模型
- 真正的系统配置接口暴露（例如前端直接拿到 `LLM_BASE_URL` 和 inferred model）
- 更细的 trace / telemetry 可视化
- 更彻底的 chunk split / 路由级懒加载

## 重要实现边界

主 session 检查时请注意以下边界是“有意如此”，不是遗漏：

### 1. 没有新增后端协议

本轮没有要求后端改字段或新增接口。  
因此前端没有实现：

- `supported_models`
- `probe-models`
- system default 配置直出接口

相关页面目前都是基于现有 API 能力做最小正确表达。

### 2. 没有做“未来模块占位”

本轮导航只保留当前后端真实支持的模块。  
没有加入：

- 用户管理
- 完整日志管理
- 未来 admin 模块空壳

### 3. 仍按桌面优先

本轮重构目标是桌面端专业工作台。  
移动端没有做完整体验承诺。

## 建议主 session 检查的重点

### 1. 视觉与交互方向是否认可

重点看：

- 顶部悬浮导航是否符合预期
- 浅银白 + 毛玻璃 + 冷蓝点缀是否是想要的方向
- 页面层级是否够“专业应用”，而非“后台模板”

### 2. Chat 的执行上下文表达是否足够清楚

重点看：

- skill 模式与 direct ask 模式的区别是否一眼可读
- provider/model/session/doc 的最终解析是否说清楚
- 错误状态是否不再“像没报错一样”

### 3. Skills 的“表单优先 + Expert 抽屉”是否满足产品化要求

重点看：

- 常规用户是否不再需要直接写 JSON
- 常用 retrieval/generation 参数是否够用
- Expert 区的存在形式是否合适

### 4. Control Plane 的系统默认表达是否足够诚实

重点看：

- 是否准确表达了 fallback order
- 是否避免假装前端已经拿到了系统配置详情

## 已完成验证

已在前端目录执行：

```bash
npm run lint
npm run build
```

结果：

- `lint` 通过
- `build` 通过

备注：

- Vite build 仍有 chunk size warning
- 当前不影响功能
- 若后续要继续优化，可做路由级 code splitting

## 建议的下一步

如果主 session 认可这一轮方向，建议下一轮按以下顺序继续：

1. 做人工走查
   - 登录
   - 文档上传与解析
   - provider 创建
   - skill 创建
   - direct ask
   - skill run
   - API key 创建复制

2. 收集真实 UI 调整意见
   - 导航高度
   - 毛玻璃强度
   - 信息密度
   - Chat 区域空间比例

3. 若要继续做产品化增强，优先补：
   - provider 多模型能力
   - 更细的 session/run 对照
   - trace 展示
   - 懒加载和 bundle 拆分

## 相关文档

- 方案原始计划：
  - [/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/frontend_phase2_improvement_plan.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/frontend_phase2_improvement_plan.md)
- 阶段总 README：
  - [/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/README.md](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension/README.md)
