#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import urlparse

import requests

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional helper
    load_dotenv = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILL_ID = "380b5ee0-6e66-46a8-8355-4b3fbd3a5d6b"
DEFAULT_QUESTION = "同一航班上，无成人陪伴儿童（8 岁）最多可承运几名？其中 5 至 10 岁年龄段有何特别限制？"
DEFAULT_API_BASE = "http://127.0.0.1:22223/api/v1"


@dataclass
class EventStamp:
    event: str
    mono_ts: float
    wall_ts: float
    iso_ts: str
    payload: dict[str, Any]


@dataclass
class DeltaStamp:
    seq: int | None
    mono_ts: float
    wall_ts: float
    iso_ts: str
    chars: int
    text: str
    inter_delta_ms: float | None = None


class AuthFailure(RuntimeError):
    pass


def utc_iso(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts if ts is not None else time.time(), tz=timezone.utc)
    return dt.isoformat()


def mono_now() -> float:
    return time.perf_counter()


def wall_now() -> float:
    return time.time()


def load_env_files() -> None:
    if load_dotenv is None:
        return
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / "frontend/.env", override=False)


def resolve_api_base() -> str:
    explicit = os.getenv("PAGEINDEX_API_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")

    vite_base = os.getenv("VITE_API_BASE_URL", "").strip()
    if vite_base:
        return vite_base.rstrip("/")

    api_host = os.getenv("API_HOST", "").strip()
    api_port = os.getenv("API_PORT", "").strip()
    if api_host and api_port:
        return f"http://{api_host}:{api_port}/api/v1"

    return DEFAULT_API_BASE


def require_api_key() -> str:
    api_key = os.getenv("PAGEINDEX_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("PAGEINDEX_API_KEY is required.")
    return api_key


def resolve_bearer_token(session: requests.Session, *, api_base: str) -> str:
    username = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
    password = os.getenv("ADMIN_PASSWORD", "changeme").strip() or "changeme"
    response = session.post(
        f"{api_base.rstrip('/')}/auth/login",
        json={"username": username, "password": password},
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=(30, 60),
    )
    if not response.ok:
        raise RuntimeError(f"Bearer login failed: HTTP {response.status_code}: {response.text}")
    payload = response.json()
    token = payload.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("Bearer login failed: missing access_token")
    return token.strip()


def redact_url(value: str | None) -> str | None:
    if not value:
        return value
    try:
        parsed = urlparse(value)
    except Exception:
        return "<redacted>"

    if not parsed.scheme or not parsed.netloc:
        return "<redacted>"

    host = parsed.hostname or "<host>"
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or ""
    if path and not path.endswith("/"):
        path = path.rsplit("/", 1)[0] + "/..." if "/" in path else "/..."
    return f"{parsed.scheme}://{host}{port}{path}"


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"api_key", "authorization", "token", "access_token", "refresh_token"}:
                redacted[key] = "<redacted>"
            elif lowered in {"base_url", "api_base", "llm_base_url"}:
                redacted[key] = redact_url(str(item) if item is not None else None)
            else:
                redacted[key] = sanitize(item)
        return redacted
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def parse_sse_events(response: requests.Response):
    buffer = ""
    decoder = response.encoding or "utf-8"
    last_byte_mono = mono_now()
    last_byte_wall = wall_now()
    for chunk in response.iter_content(chunk_size=4096):
        if not chunk:
            continue
        last_byte_mono = mono_now()
        last_byte_wall = wall_now()
        buffer += chunk.decode(decoder, errors="replace")
        while "\n\n" in buffer:
            raw_event, buffer = buffer.split("\n\n", 1)
            yield raw_event, last_byte_mono, last_byte_wall
    if buffer.strip():
        yield buffer, last_byte_mono, last_byte_wall


def parse_raw_event(raw_event: str) -> tuple[str, dict[str, Any]] | None:
    normalized = raw_event.replace("\r\n", "\n").strip()
    if not normalized:
        return None

    event = "message"
    data_lines: list[str] = []
    for line in normalized.split("\n"):
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())

    data_text = "\n".join(data_lines).strip()
    if not data_text:
        return event, {}
    return event, json.loads(data_text)


def format_ms(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.1f}"


def compute_deltas(deltas: list[DeltaStamp]) -> dict[str, Any]:
    if not deltas:
        return {
            "answer_delta_count": 0,
            "average_delta_interval_ms": None,
            "max_delta_gap_ms": None,
            "output_chars": 0,
            "output_chars_per_sec": None,
        }
    intervals = [d.inter_delta_ms for d in deltas[1:] if d.inter_delta_ms is not None]
    first_ts = deltas[0].mono_ts
    last_ts = deltas[-1].mono_ts
    span_ms = max((last_ts - first_ts) * 1000.0, 0.0)
    output_chars = sum(d.chars for d in deltas)
    return {
        "answer_delta_count": len(deltas),
        "average_delta_interval_ms": round(mean(intervals), 3) if intervals else None,
        "max_delta_gap_ms": round(max(intervals), 3) if intervals else None,
        "output_chars": output_chars,
        "output_chars_per_sec": round(output_chars / (span_ms / 1000.0), 3) if span_ms > 0 else None,
    }


def run_stream_case(
    session: requests.Session,
    *,
    api_base: str,
    auth_headers: dict[str, str],
    skill_id: str,
    question: str,
    retrieval_config: dict[str, Any],
    conversation_config: dict[str, Any] | None = None,
    generation_config: dict[str, Any] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/chat/skills/{skill_id}/run"
    payload: dict[str, Any] = {
        "question": question,
        "stream": True,
        "retrieval_config": retrieval_config,
        "conversation_config": conversation_config or {},
        "generation_config": generation_config or {"temperature": 0},
    }
    if model:
        payload["model"] = model

    request_start_mono = mono_now()
    request_start_wall = wall_now()
    response = session.post(
        url,
        json=payload,
        headers={**auth_headers, "Accept": "text/event-stream", "Content-Type": "application/json"},
        stream=True,
        timeout=(30, 3600),
    )
    headers_received_mono = mono_now()
    headers_received_wall = wall_now()
    if response.status_code >= 400:
        body = response.text
        response.close()
        if response.status_code == 401:
            raise AuthFailure(body)
        raise RuntimeError(f"HTTP {response.status_code}: {body}")

    request_id = response.headers.get("x-request-id") or response.headers.get("X-Request-ID")
    response_header_snapshot = {
        "content_type": response.headers.get("content-type"),
        "cache_control": response.headers.get("cache-control"),
        "x_accel_buffering": response.headers.get("x-accel-buffering"),
        "transfer_encoding": response.headers.get("transfer-encoding"),
        "request_id": request_id,
    }

    stamps: dict[str, EventStamp] = {}
    deltas: list[DeltaStamp] = []
    errors: list[dict[str, Any]] = []
    completed_payload: dict[str, Any] | None = None
    started_run_id: str | None = None
    stream_error: dict[str, Any] | None = None
    last_delta_ts: float | None = None
    stream_closed_mono: float | None = None
    stream_closed_wall: float | None = None

    try:
        for raw_event, event_mono_ts, event_wall_ts in parse_sse_events(response):
            parsed = parse_raw_event(raw_event)
            if not parsed:
                continue
            event_name, payload_obj = parsed
            stamps[event_name] = EventStamp(event_name, event_mono_ts, event_wall_ts, utc_iso(event_wall_ts), sanitize(payload_obj))

            if event_name == "run_started":
                started_run_id = str(payload_obj.get("run_id") or "")
            elif event_name == "status":
                status = str(payload_obj.get("status") or "")
                if status:
                    stamps[f"status:{status}"] = EventStamp(
                        f"status:{status}",
                        event_mono_ts,
                        event_wall_ts,
                        utc_iso(event_wall_ts),
                        sanitize(payload_obj),
                    )
            elif event_name == "context":
                pass
            elif event_name == "answer_delta":
                delta = str(payload_obj.get("delta") or "")
                delta_stamp = DeltaStamp(
                    seq=payload_obj.get("seq"),
                    mono_ts=event_mono_ts,
                    wall_ts=event_wall_ts,
                    iso_ts=utc_iso(event_wall_ts),
                    chars=len(delta),
                    text=delta,
                    inter_delta_ms=round((event_mono_ts - last_delta_ts) * 1000.0, 3) if last_delta_ts is not None else None,
                )
                deltas.append(delta_stamp)
                last_delta_ts = event_mono_ts
            elif event_name == "run_completed":
                completed_payload = sanitize(payload_obj)
            elif event_name == "error":
                stream_error = sanitize(payload_obj)
                errors.append(stream_error)
    finally:
        stream_closed_mono = mono_now()
        stream_closed_wall = wall_now()
        response.close()

    if not started_run_id:
        started_run_id = str(completed_payload.get("id") if completed_payload else "")

    run_details = None
    if started_run_id:
        run_resp = session.get(
            f"{api_base.rstrip('/')}/runs/{started_run_id}",
            headers={**auth_headers, "Accept": "application/json"},
            timeout=(30, 120),
        )
        if run_resp.ok:
            run_details = sanitize(run_resp.json())
        else:
            run_details = {"error": f"HTTP {run_resp.status_code}", "body": run_resp.text}

    metrics = (run_details or {}).get("metrics", {}) if isinstance(run_details, dict) else {}
    execution_context = (run_details or {}).get("execution_context", {}) if isinstance(run_details, dict) else {}
    provider_info = execution_context.get("provider", {}) if isinstance(execution_context, dict) else {}
    model_info = execution_context.get("model", {}) if isinstance(execution_context, dict) else {}
    retrieval_info = execution_context.get("retrieval", {}) if isinstance(execution_context, dict) else {}

    summary = {
        "request_start_ts": utc_iso(request_start_wall),
        "headers_received_ts": utc_iso(headers_received_wall),
        "stream_closed_ts": utc_iso(stream_closed_wall),
        "http_response_headers": response_header_snapshot,
        "run_started": stamps.get("run_started").iso_ts if stamps.get("run_started") else None,
        "status_timestamps": {
            key.split(":", 1)[1]: stamp.iso_ts
            for key, stamp in stamps.items()
            if key.startswith("status:")
        },
        "context_ts": stamps.get("context").iso_ts if stamps.get("context") else None,
        "first_answer_delta_ts": deltas[0].iso_ts if deltas else None,
        "run_completed_ts": stamps.get("run_completed").iso_ts if stamps.get("run_completed") else None,
        "error_event": stream_error,
        "run_id": started_run_id,
        "request_ms": round((headers_received_mono - request_start_mono) * 1000.0, 3),
        "metrics": metrics,
        "execution_context": execution_context,
        "provider": {
            "provider_id": provider_info.get("id"),
            "provider_name": provider_info.get("name"),
            "provider_type": provider_info.get("type"),
            "provider_resolution_source": provider_info.get("resolution_source"),
            "model": model_info.get("resolved_model"),
            "retrieval_mode": retrieval_info.get("retrieval_mode"),
        },
        "delta_summary": compute_deltas(deltas),
        "deltas": [asdict(delta) for delta in deltas],
        "backend_vs_frontend": {
            "frontend_displayed_total_ms": metrics.get("total_ms"),
            "frontend_displayed_ttft_ms": metrics.get("ttft_ms"),
            "frontend_displayed_retrieve_ms": metrics.get("retrieve_ms"),
            "frontend_displayed_answer_ms": metrics.get("answer_ms"),
            "frontend_minus_backend_total_ms": 0 if metrics.get("total_ms") is not None else None,
            "frontend_minus_backend_ttft_ms": 0 if metrics.get("ttft_ms") is not None else None,
            "frontend_minus_backend_retrieve_ms": 0 if metrics.get("retrieve_ms") is not None else None,
            "frontend_minus_backend_answer_ms": 0 if metrics.get("answer_ms") is not None else None,
        },
        "derived": {
            "connect_header_latency_ms": round((headers_received_mono - request_start_mono) * 1000.0, 3),
            "queued_ms": _ms_between(stamps, "status:accepted", "status:queued"),
            "retrieving_to_context_ms": _ms_between(stamps, "status:retrieving", "context"),
            "context_to_first_delta_ms": _ms_between_ts(
                stamps.get("context").mono_ts if stamps.get("context") else None,
                deltas[0].mono_ts if deltas else None,
            ),
            "first_delta_to_completed_ms": _ms_between_ts(
                deltas[0].mono_ts if deltas else None,
                stamps.get("run_completed").mono_ts if stamps.get("run_completed") else None,
            ),
            "last_delta_to_completed_ms": _ms_between_ts(
                deltas[-1].mono_ts if deltas else None,
                stamps.get("run_completed").mono_ts if stamps.get("run_completed") else None,
            ),
            "stream_closed_lag_ms": _ms_between_ts(
                stamps.get("run_completed").mono_ts if stamps.get("run_completed") else None,
                stream_closed_mono,
            ),
            "answer_delta_count": len(deltas),
            "average_delta_interval_ms": compute_deltas(deltas)["average_delta_interval_ms"],
            "max_delta_gap_ms": compute_deltas(deltas)["max_delta_gap_ms"],
            "output_chars": compute_deltas(deltas)["output_chars"],
            "output_chars_per_sec": compute_deltas(deltas)["output_chars_per_sec"],
            "output_tokens": metrics.get("output_tokens"),
            "output_tokens_per_sec": _rate_per_sec(metrics.get("output_tokens"), metrics.get("answer_ms")),
        },
        "raw_run": run_details,
        "errors": errors,
    }
    return summary


def _rate_per_sec(tokens: Any, duration_ms: Any) -> float | None:
    try:
        token_count = float(tokens)
        ms = float(duration_ms)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return round(token_count / (ms / 1000.0), 3)


def _ms_between(stamps: dict[str, EventStamp], start_key: str, end_key: str) -> float | None:
    start = stamps.get(start_key)
    end = stamps.get(end_key)
    if start is None or end is None:
        return None
    return round((end.mono_ts - start.mono_ts) * 1000.0, 3)


def _ms_between_ts(start_ts: float | None, end_ts: float | None) -> float | None:
    if start_ts is None or end_ts is None:
        return None
    return round((end_ts - start_ts) * 1000.0, 3)


def build_case(name: str, retrieval_mode: str, node_top_k: int | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {"retrieval_mode": retrieval_mode}
    if node_top_k is not None:
        config["node_top_k"] = node_top_k
    return {"name": name, "retrieval_config": config}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Fast Mode end-to-end latency path for PageIndex skill runs")
    parser.add_argument("--skill-id", default=DEFAULT_SKILL_ID)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--api-base-url", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--include-minimal", action="store_true", help="Attempt a minimal non-retrieval completion test if the public API exposes one.")
    args = parser.parse_args()

    load_env_files()
    api_base = (args.api_base_url or resolve_api_base()).rstrip("/")

    session = requests.Session()
    session.trust_env = False

    api_key = os.getenv("PAGEINDEX_API_KEY", "").strip()
    bearer_token = resolve_bearer_token(session, api_base=api_base)
    primary_auth_headers: dict[str, str] | None = {"X-API-Key": api_key} if api_key else None
    fallback_auth_headers = {"Authorization": f"Bearer {bearer_token}"}

    cases = [
        build_case("fast_node_top_k_1", "fast", 1),
        build_case("fast_node_top_k_3", "fast", 3),
        build_case("fast_node_top_k_5", "fast", 5),
        build_case("deep_research", "deep_research", None),
    ]

    def execute_with_auth(auth_headers: dict[str, str]) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for case in cases:
            print(f"[run] {case['name']} ...", file=sys.stderr)
            result = run_stream_case(
                session,
                api_base=api_base,
                auth_headers=auth_headers,
                skill_id=args.skill_id,
                question=args.question,
                retrieval_config=case["retrieval_config"],
            )
            result["case"] = case["name"]
            result["retrieval_config"] = case["retrieval_config"]
            collected.append(result)
        return collected

    auth_mode = "bearer"
    if primary_auth_headers is not None:
        try:
            results = execute_with_auth(primary_auth_headers)
            auth_mode = "api_key"
        except AuthFailure:
            print("[auth] PAGEINDEX_API_KEY rejected by backend; retrying with bearer token from /auth/login.", file=sys.stderr)
            results = execute_with_auth(fallback_auth_headers)
            auth_mode = "bearer_fallback"
    else:
        results = execute_with_auth(fallback_auth_headers)

    minimal_result: dict[str, Any]
    if args.include_minimal:
        minimal_result = {
            "case": "minimal_completion",
            "status": "unavailable",
            "reason": "No public non-retrieval completion endpoint is exposed in the current API surface.",
        }
    else:
        minimal_result = {
            "case": "minimal_completion",
            "status": "skipped",
            "reason": "Not requested via --include-minimal.",
        }

    artifact = {
        "generated_at": utc_iso(),
        "api_base_url": redact_url(api_base),
        "skill_id": args.skill_id,
        "question": args.question,
        "auth_mode": auth_mode,
        "results": results,
        "minimal_completion": minimal_result,
    }

    output_path = Path(args.output) if args.output else ROOT / "results" / f"b4_4_latency_compare_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    print(f"\n[artifact] {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
