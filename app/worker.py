import asyncio
import contextlib
import json
import logging
import multiprocessing
import os
import resource
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services.chat_service import mark_orphaned_chat_runs_for_retry, run_chat_run
from app.services.compliance_service import mark_orphaned_compliance_runs_for_retry, run_compliance_run
from app.services.parse_service import run_parse_job


settings = get_settings()
logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _worker_node_code_with_pid(base_code: str, pid: int) -> str:
    suffix = f"pid{pid}"
    if base_code.endswith(f":{suffix}") or f":{suffix}:" in base_code:
        return base_code
    return f"{base_code}:{suffix}"


def _worker_registry_key(node_code: str) -> str:
    return f"{settings.worker_registry_prefix}:{node_code}"


def _fallback_rss_bytes() -> tuple[int, str]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss_bytes = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
    return int(rss_bytes), "ru_maxrss"


def _current_rss_bytes() -> tuple[int, str]:
    status_path = "/proc/self/status"
    try:
        with open(status_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024, "proc_status_vmrss"
    except (FileNotFoundError, OSError, ValueError):
        pass

    statm_path = "/proc/self/statm"
    try:
        with open(statm_path, "r", encoding="utf-8") as handle:
            parts = handle.read().strip().split()
            if len(parts) >= 2:
                page_size = os.sysconf("SC_PAGE_SIZE")
                return int(parts[1]) * int(page_size), "proc_statm"
    except (FileNotFoundError, OSError, ValueError):
        pass

    return _fallback_rss_bytes()


def _build_worker_heartbeat_payload(
    *,
    worker_node_code: str,
    pid: int,
    queue_names: list[str],
    started_at: str,
    current_job: dict[str, Any] | None,
    queue_backlogs: dict[str, int] | None,
    connection_state: str,
) -> dict[str, Any]:
    return {
        "worker_node_code": worker_node_code,
        "pid": pid,
        "queues": queue_names,
        "started_at": started_at,
        "heartbeat_at": _utcnow_iso(),
        "connection_state": connection_state,
        "status": "busy" if current_job else "idle",
        "current_job": current_job,
        "queue_backlogs": queue_backlogs or {},
    }


class AsyncWorkerRuntime:
    def __init__(self) -> None:
        self.pid = os.getpid()
        self.worker_node_code = _worker_node_code_with_pid(settings.worker_node_code, self.pid)
        settings.worker_node_code = self.worker_node_code
        self.queue_names = [settings.queue_name_chat, settings.queue_name_compliance, settings.queue_name_parse]
        self.started_at = _utcnow_iso()
        self.current_job: dict[str, Any] | None = None
        self._redis = None
        self._stop_event = asyncio.Event()
        self.tasks_processed = 0

    async def _connect(self) -> None:
        import redis.asyncio as redis_async

        if self._redis is not None:
            return
        client = redis_async.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_keepalive=True,
            socket_timeout=settings.redis_socket_timeout_seconds,
            socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
            health_check_interval=settings.redis_health_check_interval_seconds,
            retry_on_timeout=True,
            client_name=self.worker_node_code,
        )
        await client.ping()
        self._redis = client
        logger.info(
            "worker_connected %s",
            json.dumps(
                {
                    "worker_node_code": self.worker_node_code,
                    "pid": self.pid,
                    "queues": self.queue_names,
                },
                ensure_ascii=False,
            ),
        )

    async def _close_redis(self) -> None:
        if self._redis is None:
            return
        await self._redis.aclose()
        self._redis = None

    async def _ensure_redis(self):
        if self._redis is None:
            await self._connect()
        return self._redis

    async def _queue_backlogs(self) -> dict[str, int]:
        client = await self._ensure_redis()
        return {
            queue_name: int(await client.llen(queue_name))
            for queue_name in self.queue_names
        }

    async def _publish_heartbeat(self, *, connection_state: str) -> None:
        client = await self._ensure_redis()
        payload = _build_worker_heartbeat_payload(
            worker_node_code=self.worker_node_code,
            pid=self.pid,
            queue_names=self.queue_names,
            started_at=self.started_at,
            current_job=self.current_job,
            queue_backlogs=await self._queue_backlogs(),
            connection_state=connection_state,
        )
        await client.set(
            _worker_registry_key(self.worker_node_code),
            json.dumps(payload, ensure_ascii=False),
            ex=settings.worker_heartbeat_ttl_seconds,
        )
        logger.info("worker_heartbeat %s", json.dumps(payload, ensure_ascii=False))

    async def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self._redis is not None:
                    await self._publish_heartbeat(connection_state="connected")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "worker_heartbeat_failed %s",
                    json.dumps(
                        {
                            "worker_node_code": self.worker_node_code,
                            "pid": self.pid,
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    ),
                )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=settings.worker_heartbeat_interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def _requeue_stale_runs(self) -> None:
        db = SessionLocal()
        try:
            requeued_ids = mark_orphaned_chat_runs_for_retry(db)
            requeued_compliance_ids = mark_orphaned_compliance_runs_for_retry(db)
        finally:
            db.close()
        if not requeued_ids and not requeued_compliance_ids:
            return
        client = await self._ensure_redis()
        for stale_run_id in requeued_ids:
            payload = json.dumps({"kind": "chat_run", "run_id": stale_run_id})
            await client.rpush(settings.queue_name_chat, payload)
            logger.warning(
                "worker_requeue_stale_run %s",
                json.dumps(
                    {
                        "worker_node_code": self.worker_node_code,
                        "pid": self.pid,
                        "run_id": stale_run_id,
                        "queue": settings.queue_name_chat,
                    },
                    ensure_ascii=False,
                ),
            )
        for stale_run_id in requeued_compliance_ids:
            payload = json.dumps({"kind": "compliance_run", "run_id": stale_run_id})
            await client.rpush(settings.queue_name_compliance, payload)
            logger.warning(
                "worker_requeue_stale_compliance_run %s",
                json.dumps(
                    {
                        "worker_node_code": self.worker_node_code,
                        "pid": self.pid,
                        "run_id": stale_run_id,
                        "queue": settings.queue_name_compliance,
                    },
                    ensure_ascii=False,
                ),
            )

    async def _handle_message(self, queue_name: str, message: dict[str, Any], backlog_after_pop: int) -> None:
        kind = message.get("kind")
        self.current_job = {
            "kind": kind,
            "queue": queue_name,
            "run_id": message.get("run_id"),
            "job_id": message.get("job_id"),
            "started_at": _utcnow_iso(),
        }
        logger.info(
            "worker_job_start %s",
            json.dumps(
                {
                    "worker_node_code": self.worker_node_code,
                    "pid": self.pid,
                    "kind": kind,
                    "run_id": message.get("run_id"),
                    "job_id": message.get("job_id"),
                    "queue": queue_name,
                    "backlog_after_pop": backlog_after_pop,
                },
                ensure_ascii=False,
            ),
        )
        try:
            if kind == "parse_job":
                await run_parse_job(message["job_id"])
            elif kind == "chat_run":
                await run_chat_run(message["run_id"])
            elif kind == "compliance_run":
                await run_compliance_run(message["run_id"])
            else:
                logger.warning(
                    "worker_unknown_message %s",
                    json.dumps(
                        {
                            "worker_node_code": self.worker_node_code,
                            "pid": self.pid,
                            "queue": queue_name,
                            "payload": message,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                )
        except Exception:
            logger.exception(
                "worker_job_failed worker_node_code=%s pid=%s kind=%s run_id=%s job_id=%s",
                self.worker_node_code,
                self.pid,
                kind,
                message.get("run_id"),
                message.get("job_id"),
            )
        finally:
            self.current_job = None

    async def run(self) -> None:
        heartbeat_task: asyncio.Task | None = None
        try:
            await self._connect()
            logger.info(
                "worker_ready %s",
                json.dumps(
                    {
                        "worker_node_code": self.worker_node_code,
                        "pid": self.pid,
                        "queues": self.queue_names,
                        "heartbeat_key": _worker_registry_key(self.worker_node_code),
                        "process_count": settings.worker_process_count,
                    },
                    ensure_ascii=False,
                ),
            )
            await self._publish_heartbeat(connection_state="connected")
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            while not self._stop_event.is_set():
                try:
                    client = await self._ensure_redis()
                    await self._requeue_stale_runs()
                    item = await client.blpop(self.queue_names, timeout=5)
                    if not item:
                        continue
                    queue_name, payload = item
                    backlog_after_pop = int(await client.llen(queue_name))
                    try:
                        message = json.loads(payload)
                    except json.JSONDecodeError:
                        logger.warning(
                            "worker_invalid_payload %s",
                            json.dumps(
                                {
                                    "worker_node_code": self.worker_node_code,
                                    "pid": self.pid,
                                    "queue": queue_name,
                                    "payload": payload,
                                },
                                ensure_ascii=False,
                            ),
                        )
                        continue
                    await self._handle_message(queue_name, message, backlog_after_pop)
                    
                    self.tasks_processed += 1
                    if self.tasks_processed >= settings.worker_max_tasks_per_child:
                        logger.info(
                            "worker_recycling %s",
                            json.dumps(
                                {"worker_node_code": self.worker_node_code, "pid": self.pid, "reason": "max_tasks_reached"},
                                ensure_ascii=False,
                            ),
                        )
                        break

                    rss_bytes, rss_source = _current_rss_bytes()
                    rss_mb = rss_bytes / (1024 * 1024)
                    if rss_mb > settings.worker_max_rss_mb:
                        logger.warning(
                            "worker_rss_exceeded %s",
                            json.dumps(
                                {
                                    "worker_node_code": self.worker_node_code,
                                    "pid": self.pid,
                                    "rss_mb": round(rss_mb, 2),
                                    "limit_mb": settings.worker_max_rss_mb,
                                    "rss_source": rss_source,
                                },
                                ensure_ascii=False,
                            ),
                        )
                        break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "worker_loop_error %s",
                        json.dumps(
                            {
                                "worker_node_code": self.worker_node_code,
                                "pid": self.pid,
                                "error_type": exc.__class__.__name__,
                                "error": str(exc),
                                "reconnect_delay_ms": settings.worker_reconnect_delay_ms,
                            },
                            ensure_ascii=False,
                        ),
                    )
                    await self._close_redis()
                    await asyncio.sleep(settings.worker_reconnect_delay_ms / 1000)
        finally:
            self._stop_event.set()
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
            if self._redis is not None:
                with contextlib.suppress(Exception):
                    await self._redis.delete(_worker_registry_key(self.worker_node_code))
            await self._close_redis()


def _run_worker_process() -> None:
    _configure_logging()
    runtime = AsyncWorkerRuntime()
    asyncio.run(runtime.run())


def main() -> None:
    _configure_logging()
    init_llm()
    if settings.task_queue_backend != "redis":
        raise RuntimeError("worker requires TASK_QUEUE_BACKEND=redis")
    if not settings.redis_url:
        raise RuntimeError("worker requires REDIS_URL")

    process_count = max(int(settings.worker_process_count), 1)
    logger.info(
        "worker_supervisor_start %s",
        json.dumps(
            {
                "requested_process_count": process_count,
                "worker_node_code": settings.worker_node_code,
            },
            ensure_ascii=False,
        ),
    )
    processes: list[multiprocessing.Process] = []
    try:
        import time
        for _ in range(process_count):
            process = multiprocessing.Process(target=_run_worker_process)
            process.start()
            processes.append(process)
            
        while True:
            for i, process in enumerate(processes):
                if not process.is_alive():
                    exit_code = process.exitcode
                    logger.warning(
                        "worker_process_died_restarting %s",
                        json.dumps({"pid": process.pid, "exit_code": exit_code}, ensure_ascii=False),
                    )
                    process.join()
                    new_process = multiprocessing.Process(target=_run_worker_process)
                    new_process.start()
                    processes[i] = new_process
            time.sleep(1)
    except KeyboardInterrupt:
        logger.warning("worker_supervisor_interrupt requested_process_count=%s", process_count)
        for process in processes:
            if process.is_alive():
                process.terminate()
        for process in processes:
            process.join()


if __name__ == "__main__":
    main()
