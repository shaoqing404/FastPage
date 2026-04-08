# Phase 2 前端改进方案

## 背景

当前 Phase 2 后端已经具备以下能力：

- `tenant` 级 API Key
- `model provider` 管理
- `provider_id` 参与 `chat/ask` 与 `chat/skills/{skill_id}/run`
- `session`
- `answer_text / answer_with_marker / citations`

但前端当前只是“把这些字段接进来了”，还没有形成正确的产品交互模型。  
你这轮测试暴露的问题，不是零散修几个按钮就能收口，而是要把前端的 provider / model / skill 配置心智统一掉。

## 已观察到的问题

### 1. API Key 创建后可见性和复制体验不足

现状：

- 创建成功后仅把明文 key 显示在页面中
- 需要手动选中复制

问题：

- 明文 key 只返回一次，这是对的
- 但前端没有提供“立即复制”动作，也没有“已复制”反馈
- 这会导致用户遗漏 key，体验很差

建议：

- 创建成功后弹出一次性 modal 或 toast 卡片
- 显示：
  - key name
  - key prefix
  - 明文 key
- 提供：
  - `Copy` 按钮
  - 点击后调用 `navigator.clipboard.writeText`
  - 成功提示 `Copied`
- modal 关闭后不再显示明文

优先级：`P0`

---

### 2. Provider 只有一个 default model，缺少“多模型”能力

现状：

- `ModelProvider` 数据结构只有一个 `default_model`
- 前端创建 provider 时只能填写一个模型名

问题：

- 这只能支撑“provider 默认模型”
- 不能支撑“同一 provider 下多个可选模型”
- 更不能支撑“根据 provider 动态提供模型候选”

这就是你遇到的核心矛盾：

- 你创建了 `deepseek` provider
- provider 的默认模型可能是 `deepseek-chat`
- 但 skill 页面和 chat 页面仍然只能从静态 `MODEL_OPTIONS` 里选 `qwen/glm/gpt`

这会直接造成：

- provider 已切到 `deepseek`
- model 仍是 `openai/qwen-plus` 之类的旧静态值
- 最终请求在后端执行时可能模型/provider 不匹配
- 轻则回答失败，重则行为不可预测

结论：

- 当前前端模型选择逻辑不再成立
- 必须进入“provider-aware model selection”

优先级：`P0`

---

### 3. Skills 页面没有基于 provider 约束 model

现状：

- skill 可以绑定 `provider_id`
- 但 `model` 仍然来自前端静态常量 `MODEL_OPTIONS`

问题：

- skill 的 `model` 应该至少满足以下之一：
  1. 使用 provider 的 `default_model`
  2. 从 provider 的 `supported_models` 中选择
  3. 允许手填，但必须有 provider 上下文提示

当前行为等价于：

- provider 是动态的
- model 是全局静态的

这两者逻辑冲突。

建议：

- `Skills` 页面中，选择 provider 后，`model` 区域切换为“provider 绑定模型输入器”
- 第一阶段最小实现：
  - 如果 provider 存在，默认填入 `provider.default_model`
  - 允许用户手动覆盖 model 文本
  - 不再把 model 强行限制在静态下拉框
- 第二阶段增强实现：
  - 后端增加 provider 可选模型清单接口
  - 或在 provider 中保存 `supported_models_json`
  - 前端按 provider 动态渲染模型下拉

优先级：`P0`

---

### 4. Chat 页面没有形成“provider + model + session”一体化执行上下文

现状：

- 页面有 provider override
- 页面有 direct ask model
- skill 自身也有 provider/model
- 但用户看不到最终“本次执行到底用的是哪个 provider 和 model”

问题：

- 对用户来说，执行上下文不透明
- 当前聊天失败时也缺少足够明确的错误呈现
- 当 provider 和 model 不匹配时，用户无法快速判断是 skill 配置问题还是 chat override 问题

建议：

- Chat 页面需要新增 `Resolved Execution Context` 区域，清楚展示：
  - mode: `skill` / `direct ask`
  - resolved provider
  - resolved model
  - session
  - selected documents
- 在提交前做前端校验：
  - skill + provider 已绑定，但 model 为空时，阻止提交
  - provider override 存在但 model 为空时，提示“需要显式 model 或使用 provider 默认 model”
- 在响应失败时，把 `detail` 明确展示，不允许静默失败

优先级：`P0`

---

### 5. “默认系统 provider / model” 对用户不可见

当前后端行为在 [app/services/provider_service.py](/Users/shaoqing/workspace/PageIndex/app/services/provider_service.py) 与 [app/core/config.py](/Users/shaoqing/workspace/PageIndex/app/core/config.py)：

- 如果 `skill.provider_id` 存在，优先用 skill provider
- 否则如果请求显式传了 `provider_id`，用它
- 否则查租户默认 provider
- 否则退回系统默认 provider

系统默认 provider 实际上是：

- `base_url = settings.llm_base_url`
- `api_key = settings.llm_api_key`
- `provider_type = "system_default"`

系统默认 model 则不是 provider 自己存的，而是从配置推断：

- 如果 `llm_base_url` 包含 `dashscope`，默认是 `openai/qwen-plus`
- 否则默认是 `gpt-4o-2024-11-20`

问题：

- 前端没有把这个“系统默认 provider”表达出来
- 所以用户不知道“没选 provider 时到底会打到哪里”

建议：

- 在 Control Plane 页面增加一张 `System Default Execution` 信息卡
- 展示：
  - current `LLM_BASE_URL`
  - inferred default model
  - fallback order
- 在 Chat 页面 provider 下拉里第一项明确写成：
  - `Use resolved provider (tenant default -> system default)`

优先级：`P1`

---

### 6. 缺少 provider 模型探测/管理设计

你提到的“自动探测”是合理诉求，但当前后端并没有模型探测接口，也没有 provider 的多模型结构。

所以这里要先做设计决策，再编码。

推荐分两步：

#### 方案 A：先做最小可用

后端扩展 `ModelProvider`：

- 增加 `supported_models_json`

前端：

- provider 创建/编辑时允许录入多个模型
- `default_model` 必须属于 `supported_models`
- skill/chat 选择 provider 后，从该 provider 的模型列表中选择

优点：

- 不依赖第三方 provider 的模型列举接口
- 对 OpenAI-compatible 场景最稳

缺点：

- 需要人工维护模型列表

#### 方案 B：再做自动探测

后端新增：

- `POST /api/v1/model-providers/{provider_id}/probe-models`

行为：

- 按 provider 类型调用对应模型列表接口，或探测约定接口
- 将结果写入 `supported_models_json`

前端：

- provider 页面增加 `Probe Models` 按钮
- 探测成功后自动回填候选模型

结论：

- Phase 2 应先做方案 A
- 方案 B 作为 Phase 2.1 或 Phase 3 增强

优先级：

- 方案 A：`P0`
- 方案 B：`P2`

---

### 7. 聊天失败缺少明确错误呈现

现状：

- 你测试时出现“无报错、无正常回答”

高概率原因：

- provider 与 model 不匹配
- 但前端只看到了一个弱提示，或者错误被 mutation 的状态切换淹没

建议：

- Chat 页面提交失败时：
  - 在聊天区顶部显示后端 `detail`
  - 保留本次提问内容，不要清空
  - 给一个 `Retry` 按钮
- 如果是 provider/model 解析失败，要在错误区显示：
  - provider name
  - requested model
  - backend detail

优先级：`P0`

## 推荐的前端改造顺序

### 第一批：必须先改

1. API Key 一次性复制交互
2. provider-aware model 选择
3. skill 页面改为：
   - provider 选择
   - model 文本框/动态候选
   - 不再只依赖静态 `MODEL_OPTIONS`
4. chat 页面改为：
   - resolved execution context
   - provider/model 校验
   - 错误清晰可见

### 第二批：紧随其后

5. Control Plane 增加：
   - system default execution 卡片
   - provider 多模型录入
6. chat 页面增强 citations 展示方式
7. session 面板增加 session messages 与 run 的对照视图

### 第三批：增强项

8. provider 模型探测
9. provider 连通性测试
10. 更细的 telemetry 与 trace 展示

## 建议的后端补充接口/字段

为了让前端改造更稳，建议后端补两项：

### 1. `ModelProvider` 增加字段

- `supported_models: string[]`

### 2. provider 探测接口

- `POST /api/v1/model-providers/{provider_id}/probe-models`

如果暂时不做自动探测，至少要先补 `supported_models`。

## UI / 风格整改要求

当前页面的核心问题不是“功能不能点”，而是视觉语言不成立。  
你说“没有科技感”，这个判断是准确的。

现状问题：

- 只是深色背景 + 玻璃面板
- 缺少明确的视觉层级
- 缺少一眼能识别的品牌调性
- 动效是“轻微 hover”，不是有节奏的系统动画
- 字体、网格、数据面板、控制面板之间没有统一的工业设计语言

建议其他 session 在正式改 UI 前，先和你做一次风格确认，至少明确以下内容：

### 需要先讨论的风格决策

1. 你要的是哪类“科技感”
   - 航电控制台
   - 科幻作战界面
   - 高级工业 HMI
   - 黑客终端风
   - 企业 AI 指挥台

2. 色彩主轴
   - 冰蓝 / 青色
   - 蓝绿荧光
   - 冷白 + 钢灰
   - 橙蓝对比

3. 动效强度
   - 轻动效
   - 明显转场
   - 高动态控制台风格

4. 信息密度
   - 克制
   - 中密度
   - 高密度仪表盘

### 对其他 session 的明确要求

- 不要继续做“普通 SaaS 深色后台模板”
- 不要只靠 `backdrop-blur` 假装科技感
- 要先给你出 `moodboard / 方向描述 / 主题 token`
- 通过你确认后再开始系统性改页面

## 建议交付给其他 session 的任务边界

其他 session 下一轮不要同时做后端和前端。  
建议只做以下前端任务：

1. 改造 Control Plane
   - API Key 一次性复制
   - provider 多模型录入
   - system default execution 卡片

2. 改造 Skills
   - provider-aware model 选择
   - retrieval/generation 配置校验

3. 改造 Chat
   - resolved execution context
   - 错误清晰展示
   - citations 更清楚地展示

4. 在动手前先和你确认 UI 风格

## 结论

当前问题的根因不是 DeepSeek 本身，而是：

- provider 已动态化
- model 仍静态化
- 前端没有把“执行上下文”表达出来

这一点不改，后续不管接 DeepSeek、Qwen、OpenAI-compatible，都会持续出现配置错位和“看起来没报错但实际不可用”的问题。
