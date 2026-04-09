import asyncio
import json
import time

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services.chat_service import mark_orphaned_chat_runs_for_retry, run_chat_run
from app.services.parse_service import run_parse_job


settings = get_settings()


def main() -> None:
    if settings.task_queue_backend != "redis":
        raise RuntimeError("worker requires TASK_QUEUE_BACKEND=redis")
    if not settings.redis_url:
        raise RuntimeError("worker requires REDIS_URL")

    import redis

    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    queue_names = [settings.queue_name_chat, settings.queue_name_parse]
    print(f"worker node={settings.worker_node_code} listening on queues={','.join(queue_names)}")
    while True:
        db = SessionLocal()
        try:
            for stale_run_id in mark_orphaned_chat_runs_for_retry(db):
                payload = json.dumps({"kind": "chat_run", "run_id": stale_run_id})
                client.rpush(settings.queue_name_chat, payload)
        finally:
            db.close()

        item = client.blpop(queue_names, timeout=5)
        if not item:
            continue
        queue_name, payload = item
        message = json.loads(payload)
        kind = message.get("kind")
        if kind == "parse_job":
            print(f"worker node={settings.worker_node_code} handling parse_job={message['job_id']}")
            asyncio.run(run_parse_job(message["job_id"]))
        elif kind == "chat_run":
            print(f"worker node={settings.worker_node_code} handling chat_run={message['run_id']}")
            asyncio.run(run_chat_run(message["run_id"]))
        else:
            print(f"worker node={settings.worker_node_code} unknown message kind={kind} queue={queue_name}")
            time.sleep(0.1)


if __name__ == "__main__":
    main()
