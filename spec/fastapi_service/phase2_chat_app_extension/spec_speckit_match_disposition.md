# SpecKit 匹配报告处理意见

来源报告：

- [results/spec_speckit_match_report.md](/Users/shaoqing/workspace/PageIndex/results/spec_speckit_match_report.md)

## 结论

报告里的主判断基本成立：

- 当前阶段 Phase 0 主体已经可收官
- Phase 1 已经进入“架构到位、能力未全部收口”的状态
- 需要立刻处理的不是“重做本阶段”，而是把剩余缺口纳入下一阶段第一批任务

## 差距项处理建议

### 1. API Key 体系

结论：

- 要改
- 不在本阶段回补
- 放到下一阶段第一优先级

原因：

- 这是 Phase 2 规划里最前置的一块
- 它会影响鉴权 principal、tenant-scope、provider 管理和外部调用方式
- 现在回补会和下一阶段目录重整产生重复工作

处理方式：

- 在 Phase 2 首批任务中新增 `api_keys` 数据模型、hash 存储、创建/列表/吊销接口
- 鉴权链路统一为 `Bearer` 或 `X-API-Key`
- 同步引入 principal 抽象，替代当前“只有 session user”的依赖输出

### 2. ChatRun 缺少 `answering` 中间态

结论：

- 要改
- 早于 API Key 完成，但仍放到下一阶段处理
- 不建议为本阶段单独出一次补丁

原因：

- 这是一个正确但轻量的合同对齐问题
- 会和下一阶段聊天执行链路升级、引用标识、provider 解析一起改更顺手

处理方式：

- 在 Phase 2 的聊天执行链路重构时补齐状态流转：
  - `accepted -> retrieving -> answering -> completed/failed`

### 3. 显式多租户/多用户管理能力

结论：

- 要改
- 明确放到下一阶段，不回灌本阶段

原因：

- 本阶段目标是单用户闭环和异步解析架构到位
- 目前字段与 tenant-scope 已经预留，继续深入会和 API Key / principal / provider 配置重叠

处理方式：

- 在 Phase 2 的“租户隔离强化”任务里统一处理
- 优先确保所有 query / mutation 通过 principal 约束 tenant

## 本阶段是否需要额外返工

不需要大规模返工。

本阶段建议只保留以下收尾动作：

- Docker 化启动目录落地
- worker 启动与节点标识收口
- spec 补全当前实际运行模式

除此之外，不再继续向本阶段塞入 API Key、多租户治理或 provider profile 这类变化。

## 对下一阶段的输入

下一阶段第一批任务建议顺序：

1. principal 抽象
2. API Key 数据模型与鉴权
3. tenant-scope 全链路检查
4. provider profile 数据模型与接口
5. chat run 状态机与引用协议升级

