# Skill Chat Stream Contract

## Scope

Phase 2 仅对 skill chat 提供流式能力：

- 统一入口：`POST /api/v1/chat/skills/{skill_id}/run` with `stream=true`
- 兼容入口：`POST /api/v1/chat/skills/{skill_id}/run/stream`

以下能力暂不在本轮实现：

- `/api/v1/chat/ask` 流式
- WebSocket
- 多路并发流复用

## Transport

- Transport: `SSE` (`text/event-stream`)
- 前端建议使用 `fetch` + `ReadableStream` 或标准 `EventSource` 兼容读取
- 每个 event 均为：

```text
event: <event_name>
data: <json>

```

## Request Body

与 `POST /api/v1/chat/skills/{skill_id}/run` 保持同构：

```json
{
  "question": "string",
  "document_id": "string|null",
  "session_id": "string|null",
  "stream": true,
  "conversation_config": {},
  "retrieval_config": {},
  "generation_config": {}
}
```

说明：

- `skill` 自身配置为父模板
- 本次请求的 `conversation_config / retrieval_config / generation_config` 为子覆盖

## Event Sequence

### 1. `run_started`

```json
{
  "run_id": "uuid",
  "session_id": "uuid|null",
  "created_at": "iso8601"
}
```

### 2. `status`

状态值：

- `accepted`
- `retrieving`
- `answering`
- `completed`
- `failed`

```json
{
  "status": "retrieving"
}
```

### 3. `context`

在 retrieval 完成后发出，用于前端直接展示有效执行上下文：

```json
{
  "execution_context": {
    "provider": {
      "id": "provider_id|null",
      "name": "provider_name|null",
      "type": "provider_type|null"
    },
    "model": {
      "resolved_model": "string"
    },
    "conversation": {
      "query_rewrite_with_history": true,
      "include_history": true,
      "include_assistant_messages": true,
      "history_turn_limit": 4,
      "history_token_budget": 1800,
      "history_used": true,
      "history_messages_used": 6,
      "history_turns_used": 3,
      "history_token_estimate": 512
    },
    "retrieval": {
      "query": "standalone query",
      "rewritten_query": "standalone query|null",
      "rewrite_applied": true,
      "top_k": 5,
      "selection_mode": "outline_llm",
      "max_context_pages": 12,
      "max_context_tokens": 24000
    },
    "generation": {
      "temperature": 0.2
    }
  }
}
```

### 4. `answer_delta`

```json
{
  "delta": "本次新增文本",
  "seq": 12
}
```

### 5. `run_completed`

始终返回完整 `ChatRunOut`，前端可直接回落到既有 runs/session/messages 数据结构。

注意：

- `citations`
- `selected_sections`
- `metrics`

本轮只在 final event 中返回，不在中间流事件里增量下发。

### 6. `error`

当流已建立后发生异常，后端通过流内 error event 返回：

```json
{
  "code": "skill_stream_failed",
  "message": "error text",
  "detail": "error text"
}
```

## Error Semantics

### Before stream starts

以下错误仍走普通 HTTP 非 200：

- 鉴权失败
- `skill_id` 不存在
- `document_id` 不存在
- 文档未完成解析
- `session_id` 与 `skill` 作用域冲突
- 参数校验失败

### After stream starts

以下错误走流内事件：

- retrieval 阶段失败
- final answer 阶段失败
- provider 调用失败

后端会补发：

- `status=failed`
- `error`

## Abort

- 客户端主动断开连接时，后端做 best-effort 停止流
- 当前实现会将 run 标记为 `failed`
- `metrics.error = "client aborted stream"`

## Notes

- 本轮为最小可用流式协议，不保证 token usage 为 provider 原始 usage；当前 final metrics 可能使用近似 token 估算。
- 当前流式只对最终答案增量输出，retrieval/query rewrite 仍在服务端内部完成。
