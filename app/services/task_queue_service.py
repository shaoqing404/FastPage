import asyncio
import json

from app.core.config import get_settings


settings = get_settings()


class BaseTaskQueue:
    def enqueue_parse_job(self, job_id: str) -> None:
        raise NotImplementedError


class LocalTaskQueue(BaseTaskQueue):
    def enqueue_parse_job(self, job_id: str) -> None:
        from app.services.parse_service import run_parse_job

        asyncio.create_task(run_parse_job(job_id))


class RedisTaskQueue(BaseTaskQueue):
    def __init__(self) -> None:
        if not settings.redis_url:
            raise RuntimeError("REDIS_URL is required for redis task queue backend")
        import redis

        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def enqueue_parse_job(self, job_id: str) -> None:
        payload = json.dumps({"kind": "parse_job", "job_id": job_id})
        self.client.rpush(settings.queue_name_parse, payload)


def get_task_queue() -> BaseTaskQueue:
    if settings.task_queue_backend == "redis":
        return RedisTaskQueue()
    return LocalTaskQueue()


task_queue = get_task_queue()


def enqueue_parse_job(job_id: str) -> None:
    task_queue.enqueue_parse_job(job_id)
