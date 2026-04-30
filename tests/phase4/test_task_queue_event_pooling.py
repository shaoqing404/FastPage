import asyncio
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("TASK_QUEUE_BACKEND", "local")
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.services import task_queue_service


class TestTaskQueueEventPooling(unittest.TestCase):
    def tearDown(self):
        asyncio.run(task_queue_service._reset_redis_publish_client())

    def test_redis_event_publish_reuses_client_for_chat_and_runtime_events(self):
        clients = []

        def from_url(*args, **kwargs):
            client = MagicMock()
            client.publish = AsyncMock()
            client.aclose = AsyncMock()
            clients.append(client)
            return client

        redis_module = types.ModuleType("redis")
        redis_async_module = types.ModuleType("redis.asyncio")
        redis_async_module.Redis = MagicMock()
        redis_async_module.Redis.from_url = MagicMock(side_effect=from_url)
        redis_module.asyncio = redis_async_module

        async def scenario():
            await task_queue_service.publish_chat_event("run_1", {"event": "answer_delta", "data": {"delta": "a"}})
            await task_queue_service.publish_runtime_observation("chat", "run_1", {"event": "step_started"})
            await task_queue_service.publish_chat_event("run_1", {"event": "answer_delta", "data": {"delta": "b"}})

        with patch.dict(sys.modules, {"redis": redis_module, "redis.asyncio": redis_async_module}):
            with patch.object(task_queue_service.settings, "task_queue_backend", "redis"), patch.object(
                task_queue_service.settings,
                "redis_url",
                "redis://localhost:6379/0",
            ):
                asyncio.run(scenario())

        self.assertEqual(redis_async_module.Redis.from_url.call_count, 1)
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0].publish.await_count, 3)
        clients[0].aclose.assert_not_awaited()

    def test_redis_event_publish_rebuilds_client_after_publish_failure(self):
        first_client = MagicMock()
        first_client.publish = AsyncMock(side_effect=ConnectionError("stale connection"))
        first_client.aclose = AsyncMock()
        second_client = MagicMock()
        second_client.publish = AsyncMock()
        second_client.aclose = AsyncMock()

        redis_module = types.ModuleType("redis")
        redis_async_module = types.ModuleType("redis.asyncio")
        redis_async_module.Redis = MagicMock()
        redis_async_module.Redis.from_url = MagicMock(side_effect=[first_client, second_client])
        redis_module.asyncio = redis_async_module

        async def scenario():
            await task_queue_service.publish_chat_event("run_1", {"event": "answer_delta", "data": {"delta": "a"}})

        with patch.dict(sys.modules, {"redis": redis_module, "redis.asyncio": redis_async_module}):
            with patch.object(task_queue_service.settings, "task_queue_backend", "redis"), patch.object(
                task_queue_service.settings,
                "redis_url",
                "redis://localhost:6379/0",
            ):
                asyncio.run(scenario())

        self.assertEqual(redis_async_module.Redis.from_url.call_count, 2)
        first_client.publish.assert_awaited_once()
        first_client.aclose.assert_awaited_once()
        second_client.publish.assert_awaited_once()
        second_client.aclose.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
