import asyncio
import inspect
import json
import logging
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.core.config import get_settings


settings = get_settings()
logger = logging.getLogger(__name__)


def _redis_client_kwargs() -> dict[str, Any]:
    return {
        "decode_responses": True,
        "socket_keepalive": True,
        "socket_timeout": settings.redis_socket_timeout_seconds,
        "socket_connect_timeout": settings.redis_socket_connect_timeout_seconds,
        "health_check_interval": settings.redis_health_check_interval_seconds,
        "retry_on_timeout": True,
    }


def chat_event_channel(run_id: str) -> str:
    return f"pageindex:chat:events:{run_id}"


class BaseTaskQueue:
    def enqueue_parse_job(self, job_id: str) -> None:
        raise NotImplementedError

    def enqueue_chat_run(self, run_id: str) -> None:
        raise NotImplementedError

    def enqueue_compliance_run(self, run_id: str) -> None:
        raise NotImplementedError


class LocalTaskQueue(BaseTaskQueue):
    def enqueue_parse_job(self, job_id: str) -> None:
        from app.services.parse_service import run_parse_job

        asyncio.create_task(run_parse_job(job_id))

    def enqueue_chat_run(self, run_id: str) -> None:
        from app.services.chat_service import run_chat_run

        asyncio.create_task(run_chat_run(run_id))

    def enqueue_compliance_run(self, run_id: str) -> None:
        from app.services.compliance_service import run_compliance_run

        asyncio.create_task(run_compliance_run(run_id))


class RedisTaskQueue(BaseTaskQueue):
    def __init__(self) -> None:
        if not settings.redis_url:
            raise RuntimeError("REDIS_URL is required for redis task queue backend")
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - environment fallback
            raise RuntimeError("redis package is not installed") from exc

        self.client = redis.Redis.from_url(settings.redis_url, **_redis_client_kwargs())

    def enqueue_parse_job(self, job_id: str) -> None:
        payload = json.dumps({"kind": "parse_job", "job_id": job_id})
        self.client.rpush(settings.queue_name_parse, payload)

    def enqueue_chat_run(self, run_id: str) -> None:
        payload = json.dumps({"kind": "chat_run", "run_id": run_id})
        self.client.rpush(settings.queue_name_chat, payload)

    def enqueue_compliance_run(self, run_id: str) -> None:
        payload = json.dumps({"kind": "compliance_run", "run_id": run_id})
        self.client.rpush(settings.queue_name_compliance, payload)


class BaseChatEventSubscription:
    async def next_event(self, timeout: float | None = None) -> dict:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


class LocalChatEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[str | None]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, payload: str) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(channel, []))
        for queue in subscribers:
            await queue.put(payload)

    async def close(self, channel: str) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(channel, []))
        for queue in subscribers:
            await queue.put(None)

    async def register(self, channel: str, queue: asyncio.Queue[str | None]) -> None:
        async with self._lock:
            self._subscribers.setdefault(channel, []).append(queue)

    async def unregister(self, channel: str, queue: asyncio.Queue[str | None]) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(channel, [])
            if queue in subscribers:
                subscribers.remove(queue)
            if not subscribers and channel in self._subscribers:
                self._subscribers.pop(channel, None)


_local_chat_event_bus = LocalChatEventBus()
_redis_publish_client: Any | None = None
_redis_publish_client_url: str | None = None
_redis_publish_client_lock = asyncio.Lock()


class LocalChatEventSubscription(BaseChatEventSubscription):
    def __init__(self, channel: str) -> None:
        self.channel = channel
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def start(self) -> "LocalChatEventSubscription":
        await _local_chat_event_bus.register(self.channel, self.queue)
        return self

    async def next_event(self, timeout: float | None = None) -> dict:
        if timeout is None:
            payload = await self.queue.get()
        else:
            payload = await asyncio.wait_for(self.queue.get(), timeout=timeout)
        if payload is None:
            raise StopAsyncIteration
        return json.loads(payload)

    async def close(self) -> None:
        await _local_chat_event_bus.unregister(self.channel, self.queue)


class RedisChatEventSubscription(BaseChatEventSubscription):
    def __init__(self, channel: str) -> None:
        import redis.asyncio as redis_async

        self.channel = channel
        self.client = redis_async.Redis.from_url(settings.redis_url, **_redis_client_kwargs())
        self.pubsub = self.client.pubsub()

    async def start(self) -> "RedisChatEventSubscription":
        await self.pubsub.subscribe(self.channel)
        return self

    async def next_event(self, timeout: float | None = None) -> dict:
        while True:
            if timeout is None:
                message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    await asyncio.sleep(0.05)
                    continue
            else:
                deadline = asyncio.get_running_loop().time() + timeout
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    message = await self.pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=min(remaining, 1.0),
                    )
                    if message is not None:
                        break
                if message is None:
                    raise asyncio.TimeoutError
            data = message.get("data") if message else None
            if not data:
                continue
            return json.loads(data)

    async def close(self) -> None:
        await self.pubsub.unsubscribe(self.channel)
        await self.pubsub.aclose()
        await self.client.aclose()


async def _close_redis_publish_client(client: Any) -> None:
    try:
        close = getattr(client, "aclose", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.warning("Failed to close Redis event publish client: %s", exc)


async def _get_redis_publish_client() -> Any:
    global _redis_publish_client, _redis_publish_client_url

    async with _redis_publish_client_lock:
        if _redis_publish_client is not None and _redis_publish_client_url == settings.redis_url:
            return _redis_publish_client

        previous_client = _redis_publish_client
        _redis_publish_client = None
        _redis_publish_client_url = None
        if previous_client is not None:
            await _close_redis_publish_client(previous_client)

        import redis.asyncio as redis_async

        _redis_publish_client = redis_async.Redis.from_url(settings.redis_url, **_redis_client_kwargs())
        _redis_publish_client_url = settings.redis_url
        return _redis_publish_client


async def _reset_redis_publish_client(client: Any | None = None) -> None:
    global _redis_publish_client, _redis_publish_client_url

    client_to_close = None
    async with _redis_publish_client_lock:
        if client is not None and _redis_publish_client is not client:
            return
        client_to_close = _redis_publish_client
        _redis_publish_client = None
        _redis_publish_client_url = None

    if client_to_close is not None:
        await _close_redis_publish_client(client_to_close)


async def _publish_redis_channel_event(channel: str, payload: str) -> None:
    for attempt in range(2):
        client = await _get_redis_publish_client()
        try:
            await client.publish(channel, payload)
            return
        except Exception as exc:
            await _reset_redis_publish_client(client)
            if attempt == 1:
                raise
            logger.warning("Redis event publish failed; rebuilding publish client: %s", exc)


async def _publish_channel_event(channel: str, payload: str) -> None:
    if settings.task_queue_backend == "redis":
        try:
            await _publish_redis_channel_event(channel, payload)
        except ImportError:  # pragma: no cover - environment fallback
            await _local_chat_event_bus.publish(channel, payload)
        return
    await _local_chat_event_bus.publish(channel, payload)


async def _open_channel_subscription(channel: str) -> BaseChatEventSubscription:
    if settings.task_queue_backend == "redis":
        try:
            return await RedisChatEventSubscription(channel).start()
        except ImportError:  # pragma: no cover - environment fallback
            return await LocalChatEventSubscription(channel).start()
    return await LocalChatEventSubscription(channel).start()


async def publish_chat_event(run_id: str, event: dict) -> None:
    payload = json.dumps(jsonable_encoder(event), ensure_ascii=False)
    channel = chat_event_channel(run_id)
    await _publish_channel_event(channel, payload)


async def close_chat_event_stream(run_id: str) -> None:
    if settings.task_queue_backend == "redis":
        return
    await _local_chat_event_bus.close(chat_event_channel(run_id))


async def open_chat_event_subscription(run_id: str) -> BaseChatEventSubscription:
    channel = chat_event_channel(run_id)
    return await _open_channel_subscription(channel)


def get_task_queue() -> BaseTaskQueue:
    if settings.task_queue_backend == "redis":
        try:
            return RedisTaskQueue()
        except RuntimeError as exc:
            logger.warning("Falling back to local task queue: %s", exc)
    return LocalTaskQueue()


task_queue = get_task_queue()


def enqueue_parse_job(job_id: str) -> None:
    task_queue.enqueue_parse_job(job_id)


def enqueue_chat_run(run_id: str) -> None:
    task_queue.enqueue_chat_run(run_id)


def runtime_observation_channel(run_kind: str, run_id: str) -> str:
    return f"pageindex:runtime:observations:{run_kind}:{run_id}"


async def publish_runtime_observation(run_kind: str, run_id: str, event: dict) -> None:
    payload = json.dumps(jsonable_encoder(event), ensure_ascii=False)
    await _publish_channel_event(runtime_observation_channel(run_kind, run_id), payload)


async def open_runtime_observation_subscription(run_kind: str, run_id: str) -> BaseChatEventSubscription:
    return await _open_channel_subscription(runtime_observation_channel(run_kind, run_id))


def enqueue_compliance_run(run_id: str) -> None:
    task_queue.enqueue_compliance_run(run_id)
