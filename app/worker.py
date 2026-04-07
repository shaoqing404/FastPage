import asyncio
import json
import time

from app.core.config import get_settings
from app.services.parse_service import run_parse_job


settings = get_settings()


def main() -> None:
    if settings.task_queue_backend != "redis":
        raise RuntimeError("worker requires TASK_QUEUE_BACKEND=redis")
    if not settings.redis_url:
        raise RuntimeError("worker requires REDIS_URL")

    import redis

    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    queue_name = settings.queue_name_parse
    print(f"worker node={settings.worker_node_code} listening on queue={queue_name}")
    while True:
        item = client.blpop(queue_name, timeout=5)
        if not item:
            continue
        _, payload = item
        message = json.loads(payload)
        kind = message.get("kind")
        if kind == "parse_job":
            print(f"worker node={settings.worker_node_code} handling parse_job={message['job_id']}")
            asyncio.run(run_parse_job(message["job_id"]))
        else:
            print(f"worker node={settings.worker_node_code} unknown message kind={kind}")
            time.sleep(0.1)


if __name__ == "__main__":
    main()
