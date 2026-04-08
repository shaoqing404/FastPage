# Phase Transition Notes

## 当前阶段收官结论

当前系统已经不再是单进程 FastAPI demo，而是标准的两类进程协作：

- API service
- worker service

配套基础设施：

- MySQL: 元数据与状态
- Redis: 后台任务队列
- MinIO: PDF 与结构化产物

## 当前实际运行规则

### API service

负责：

- HTTP API
- 登录、文档、技能、问答入口
- 创建 `ParseJob` / `ChatRun`
- 写入 Redis 队列

不负责：

- 长耗时 PDF 解析执行

### worker service

负责：

- 消费 `pageindex:parse`
- 执行 PDF 解析
- 回写 `ParseJob` / `DocumentVersion` / `Document` 状态

## 已知关键运维点

- 如果 `TASK_QUEUE_BACKEND=redis` 且 worker 未启动：
  - 上传会成功
  - `ParseJob` 会创建
  - 前端进度会停留在 `0%`
  - Redis 队列长度会增长

- worker 启动命令必须使用项目解释器：

```bash
.venv/bin/python -m app.worker
```

不能依赖系统 `python` 或其他 conda 环境。

## Docker 化收官交付

新增：

- [docker/README.md](/Users/shaoqing/workspace/PageIndex/docker/README.md)
- [docker/Dockerfile](/Users/shaoqing/workspace/PageIndex/docker/Dockerfile)
- [docker/docker-compose.yml](/Users/shaoqing/workspace/PageIndex/docker/docker-compose.yml)
- [docker/start.sh](/Users/shaoqing/workspace/PageIndex/docker/start.sh)
- `docker/.env`
- [docker/.env.example](/Users/shaoqing/workspace/PageIndex/docker/.env.example)

目标：

- 用一个启动脚本同时拉起 api + 多 worker
- 通过 `docker/.env` 统一配置 MySQL / Redis / MinIO / LLM / CORS
- worker 节点带外部编码前缀，便于日志识别

## 下一阶段边界

Phase 2 开始后，不再把新增的测试结论或临时设计散放在 `results/` 或根目录。

本阶段之后的临时产物与阶段性记录统一放在：

- [spec/fastapi_service/phase2_chat_app_extension](/Users/shaoqing/workspace/PageIndex/spec/fastapi_service/phase2_chat_app_extension)

## 近期后端对齐更新

- `chat_sessions` 已升级为可选 `skill_id` 作用域
- skill 聊天不再只是前端按 `skill_id + session_id` 过滤 `runs` 的近似模拟
- 新增后端接口：
  - `POST /api/v1/chat/skills/{skill_id}/sessions`
  - `GET /api/v1/chat/skills/{skill_id}/sessions`
  - `GET /api/v1/chat/skills/{skill_id}/sessions/{session_id}`
  - `GET /api/v1/chat/skills/{skill_id}/sessions/{session_id}/messages`
- `POST /api/v1/chat/skills/{skill_id}/run` 已升级为最小可用真多轮：
  - 读取当前 skill session 最近历史消息
  - 按 `history_turn_limit + history_token_budget` 裁剪
  - retrieval 侧先做 query rewrite
  - generation 侧直接注入 conversation context
  - history 为空时自动退化为单轮
  - rewrite 失败时回退原 question，不掩盖主流程错误
- 技能模板新增共享层 `conversation_config`
- `ChatRun` 新增 `execution_context`，用于前端直接展示本次有效执行配置
- 兼容保留：
  - 原 `/api/v1/chat/sessions`
  - 原 `/api/v1/chat/sessions/{session_id}/messages`
