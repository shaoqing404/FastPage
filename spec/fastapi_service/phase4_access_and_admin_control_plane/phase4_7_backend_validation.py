#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import default_llm_model, get_settings  # noqa: E402


DEFAULT_BASE_URL = "http://127.0.0.1:22223"
DEFAULT_OUTPUT = ROOT / "results" / "phase4_7_backend_validation_latest.json"
DEFAULT_PDF = ROOT / "examples" / "documents" / "attention-residuals.pdf"
DEFAULT_DIRECT_QUESTION = "请概括这份文档的标题或主题。"
DEFAULT_SKILL_QUESTION = "请基于这份文档给出一句简短摘要。"


class ValidationError(RuntimeError):
    pass


class ValidationFailure(ValidationError):
    def __init__(self, message: str, *, created: dict[str, str | None], checks: dict[str, object], cleanup: dict[str, object]) -> None:
        super().__init__(message)
        self.created = created
        self.checks = checks
        self.cleanup = cleanup


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    api_key: str | None = None,
    json_payload: dict | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
    expected_status: int | tuple[int, ...] = 200,
) -> tuple[int, object]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if api_key:
        headers["X-API-Key"] = api_key
    payload = body
    if json_payload is not None:
        payload = _json_bytes(json_payload)
        headers["Content-Type"] = "application/json"
    elif content_type is not None:
        headers["Content-Type"] = content_type

    request = urllib.request.Request(url, data=payload, method=method, headers=headers)
    expected = (expected_status,) if isinstance(expected_status, int) else expected_status

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
        if status not in expected:
            detail = raw.decode("utf-8", errors="replace")
            raise ValidationError(f"{method} {url} -> {status}: {detail}") from exc
        return status, _decode_response(raw)
    except urllib.error.URLError as exc:
        raise ValidationError(f"{method} {url} failed: {exc}") from exc

    if status not in expected:
        detail = raw.decode("utf-8", errors="replace")
        raise ValidationError(f"{method} {url} -> {status}: {detail}")
    return status, _decode_response(raw)


def _decode_response(raw: bytes) -> object:
    if not raw:
        return None
    text = raw.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _multipart_body(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"pageindex-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )

    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    file_bytes = file_path.read_bytes()
    chunks.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode("utf-8"),
            f"Content-Type: {mime}\r\n\r\n".encode("utf-8"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _path(base_url: str, api_path: str) -> str:
    return f"{base_url.rstrip('/')}{api_path}"


def login(base_url: str, username: str, password: str) -> dict:
    _, payload = _request(
        "POST",
        _path(base_url, "/api/v1/auth/login"),
        json_payload={"username": username, "password": password},
    )
    _assert(isinstance(payload, dict), "login did not return JSON payload")
    return payload


def switch_context(base_url: str, token: str, workspace_id: str) -> dict:
    _, payload = _request(
        "POST",
        _path(base_url, "/api/v1/auth/context/switch"),
        token=token,
        json_payload={"workspace_id": workspace_id},
    )
    _assert(isinstance(payload, dict), "context switch did not return JSON payload")
    return payload


def change_password(base_url: str, token: str, current_password: str, new_password: str) -> dict:
    _, payload = _request(
        "POST",
        _path(base_url, "/api/v1/auth/change-password"),
        token=token,
        json_payload={"current_password": current_password, "new_password": new_password},
    )
    _assert(isinstance(payload, dict), "change-password did not return JSON payload")
    return payload


def poll_parse_job(base_url: str, token: str, job_id: str, *, timeout_seconds: int = 180) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        _, payload = _request("GET", _path(base_url, f"/api/v1/jobs/{job_id}"), token=token)
        _assert(isinstance(payload, dict), "job payload was not JSON")
        status = payload["status"]
        if status in {"index_ready", "failed"}:
            return payload
        time.sleep(2)
    raise ValidationError(f"parse job {job_id} did not finish within {timeout_seconds}s")


def load_runtime_defaults() -> dict[str, str]:
    settings = get_settings()
    _assert(bool(settings.llm_base_url), "llm_base_url is empty in local settings")
    _assert(bool(settings.llm_api_key), "llm_api_key is empty in local settings")
    return {
        "provider_base_url": settings.llm_base_url,
        "provider_api_key": settings.llm_api_key,
        "provider_model": default_llm_model(),
    }


def cleanup_success(base_url: str, admin_token: str, user_token: str, created: dict[str, str | None]) -> dict[str, object]:
    remaining: list[str] = []

    def best_effort(method: str, api_path: str, *, token: str, json_payload: dict | None = None, expected: tuple[int, ...] = (200, 204, 404, 409, 400)) -> None:
        try:
            _request(method, _path(base_url, api_path), token=token, json_payload=json_payload, expected_status=expected)
        except Exception:
            remaining.append(api_path)

    if created.get("api_key_id"):
        best_effort("DELETE", f"/api/v1/auth/apikeys/{created['api_key_id']}", token=user_token)
    if created.get("skill_id"):
        best_effort("DELETE", f"/api/v1/skills/{created['skill_id']}", token=user_token)
    if created.get("document_id"):
        best_effort("DELETE", f"/api/v1/documents/{created['document_id']}", token=user_token)
    if created.get("knowledge_base_id") and created.get("workspace_id"):
        best_effort(
            "DELETE",
            f"/api/v1/workspaces/{created['workspace_id']}/knowledge-bases/{created['knowledge_base_id']}",
            token=user_token,
        )
    if created.get("provider_id"):
        best_effort("DELETE", f"/api/v1/model-providers/{created['provider_id']}", token=user_token)
    if created.get("workspace_id"):
        best_effort("POST", f"/api/v1/platform/workspaces/{created['workspace_id']}/archive", token=admin_token)
    if created.get("user_id"):
        best_effort(
            "PATCH",
            f"/api/v1/platform/users/{created['user_id']}",
            token=admin_token,
            json_payload={"is_active": False, "can_create_workspace": False, "is_platform_admin": False},
        )

    return {
        "status": "completed" if not remaining else "partial",
        "retained_for_failure_analysis": False,
        "remaining_artifacts": remaining,
    }


def run_validation(args: argparse.Namespace) -> dict[str, object]:
    defaults = load_runtime_defaults()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = timestamp[-8:]
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path = Path(args.pdf).resolve()
    _assert(pdf_path.exists(), f"validation pdf does not exist: {pdf_path}")

    created: dict[str, str | None] = {
        "user_id": None,
        "workspace_id": None,
        "provider_id": None,
        "knowledge_base_id": None,
        "document_id": None,
        "skill_id": None,
        "api_key_id": None,
        "session_id": None,
        "parse_job_id": None,
        "direct_run_id": None,
        "skill_run_id": None,
    }
    checks: dict[str, object] = {}
    cleanup: dict[str, object] = {
        "status": "not_started",
        "retained_for_failure_analysis": False,
        "remaining_artifacts": [],
    }

    try:
        admin_login = login(args.base_url, args.admin_username, args.admin_password)
        admin_token = admin_login["access_token"]
        admin_user = admin_login["user"]

        create_payload = {
            "username": f"phase47_val_{suffix}",
            "password": secrets.token_urlsafe(12),
            "email": f"phase47+{timestamp}@example.test",
            "is_active": True,
            "can_create_workspace": True,
            "is_platform_admin": False,
        }
        _, created_user = _request(
            "POST",
            _path(args.base_url, "/api/v1/platform/users"),
            token=admin_token,
            json_payload=create_payload,
            expected_status=201,
        )
        _assert(isinstance(created_user, dict), "platform user create did not return JSON")
        created["user_id"] = created_user["id"]
        checks["platform_user_create"] = {"user_id": created["user_id"], "email": created_user["email"]}

        login_password = create_payload["password"]
        if args.exercise_password_reset:
            _, reset_payload = _request(
                "POST",
                _path(args.base_url, f"/api/v1/platform/users/{created['user_id']}/reset-password"),
                token=admin_token,
            )
            _assert(isinstance(reset_payload, dict), "reset-password did not return JSON")
            temp_password = reset_payload["temporary_password"]
            reset_login = login(args.base_url, create_payload["username"], temp_password)
            changed = change_password(args.base_url, reset_login["access_token"], temp_password, create_payload["password"])
            login_password = create_payload["password"]
            checks["password_reset_flow"] = {
                "performed": True,
                "must_change_password_after_reset": reset_login["user"]["must_change_password"],
                "must_change_password_after_change": changed["user"]["must_change_password"],
            }
        else:
            checks["password_reset_flow"] = {"performed": False}

        user_login = login(args.base_url, create_payload["username"], login_password)
        user_token = user_login["access_token"]
        default_workspace_id = user_login["workspace"]["id"]
        checks["validation_user_login"] = {
            "user_id": user_login["user"]["id"],
            "workspace_id": default_workspace_id,
        }

        _, workspace_list_before = _request("GET", _path(args.base_url, "/api/v1/workspaces"), token=user_token)
        _assert(isinstance(workspace_list_before, list), "workspace list did not return list")
        _assert(any(item["id"] == default_workspace_id for item in workspace_list_before), "default workspace missing from workspace list")
        checks["workspace_list_before_create"] = {"count": len(workspace_list_before)}

        _, workspace_create = _request(
            "POST",
            _path(args.base_url, "/api/v1/workspaces"),
            token=user_token,
            json_payload={"name": f"Phase47 Validation {suffix}", "slug": f"phase47-validation-{suffix.lower()}"},
            expected_status=201,
        )
        _assert(isinstance(workspace_create, dict), "workspace create did not return JSON")
        user_token = workspace_create["access_token"]
        created["workspace_id"] = workspace_create["workspace"]["id"]
        _assert(workspace_create["workspace_membership"]["role"] == "founder", "workspace create did not return founder context")
        checks["workspace_create"] = {
            "workspace_id": created["workspace_id"],
            "workspace_role": workspace_create["workspace_membership"]["role"],
        }

        switched_default = switch_context(args.base_url, user_token, default_workspace_id)
        _assert(switched_default["workspace"]["id"] == default_workspace_id, "context switch to default workspace failed")
        _, default_doc_get = _request(
            "GET",
            _path(args.base_url, "/api/v1/documents/not-a-real-doc"),
            token=switched_default["access_token"],
            expected_status=404,
        )
        checks["context_switch_to_default"] = {
            "workspace_id": switched_default["workspace"]["id"],
            "negative_probe": default_doc_get,
        }

        switched_back = switch_context(args.base_url, switched_default["access_token"], created["workspace_id"])
        _assert(switched_back["workspace"]["id"] == created["workspace_id"], "context switch back to validation workspace failed")
        user_token = switched_back["access_token"]
        _, workspace_list_after = _request("GET", _path(args.base_url, "/api/v1/workspaces"), token=user_token)
        _assert(isinstance(workspace_list_after, list), "workspace list after create did not return list")
        _assert(any(item["id"] == created["workspace_id"] for item in workspace_list_after), "created workspace missing from workspace list")
        checks["workspace_list_after_create"] = {"count": len(workspace_list_after)}

        _, api_key_payload = _request(
            "POST",
            _path(args.base_url, "/api/v1/auth/apikeys"),
            token=user_token,
            json_payload={"name": f"phase47-validation-key-{suffix.lower()}"},
        )
        _assert(isinstance(api_key_payload, dict), "api key create did not return JSON")
        created["api_key_id"] = api_key_payload["id"]
        api_key_value = api_key_payload["api_key"]
        checks["api_key_create"] = {"api_key_id": created["api_key_id"]}

        status_user_list, denied_user_list = _request(
            "GET",
            _path(args.base_url, "/api/v1/platform/users"),
            api_key=api_key_value,
            expected_status=403,
        )
        status_user_portrait, denied_user_portrait = _request(
            "GET",
            _path(args.base_url, f"/api/v1/platform/users/{created['user_id']}/access-portrait"),
            api_key=api_key_value,
            expected_status=403,
        )
        _assert(status_user_list == 403 and status_user_portrait == 403, "platform routes did not reject API key access")
        checks["platform_api_key_denied"] = {
            "users_status": status_user_list,
            "portrait_status": status_user_portrait,
            "users_detail": denied_user_list,
            "portrait_detail": denied_user_portrait,
        }

        _, knowledge_base = _request(
            "POST",
            _path(args.base_url, f"/api/v1/workspaces/{created['workspace_id']}/knowledge-bases"),
            token=user_token,
            json_payload={
                "name": f"Phase47 Validation KB {suffix}",
                "description": "Phase 4.7 runtime validation knowledge base",
                "visibility": "private",
                "retrieval_profile": {"top_k": 4},
            },
        )
        _assert(isinstance(knowledge_base, dict), "knowledge base create did not return JSON")
        created["knowledge_base_id"] = knowledge_base["id"]
        checks["knowledge_base_create"] = {"knowledge_base_id": created["knowledge_base_id"]}

        _, provider = _request(
            "POST",
            _path(args.base_url, "/api/v1/model-providers"),
            token=user_token,
            json_payload={
                "provider_type": "openai_compatible",
                "name": f"phase47-validation-provider-{suffix.lower()}",
                "base_url": defaults["provider_base_url"],
                "api_key": defaults["provider_api_key"],
                "default_model": defaults["provider_model"],
                "supported_models": [],
                "extra_headers": {},
                "enabled": True,
                "is_default": False,
            },
        )
        _assert(isinstance(provider, dict), "provider create did not return JSON")
        created["provider_id"] = provider["id"]
        _, probed_provider = _request(
            "POST",
            _path(args.base_url, f"/api/v1/model-providers/{created['provider_id']}/probe-models"),
            token=user_token,
        )
        _assert(isinstance(probed_provider, dict), "probe-models did not return JSON")
        checks["provider_create_and_probe"] = {
            "provider_id": created["provider_id"],
            "default_model": probed_provider["default_model"],
            "supported_models_count": len(probed_provider.get("supported_models", [])),
        }

        body, content_type = _multipart_body({"uploaded_via_kb_id": created["knowledge_base_id"]}, "file", pdf_path)
        _, upload_payload = _request(
            "POST",
            _path(args.base_url, "/api/v1/documents/upload"),
            token=user_token,
            body=body,
            content_type=content_type,
        )
        _assert(isinstance(upload_payload, dict), "document upload did not return JSON")
        created["document_id"] = upload_payload["document_id"]
        checks["document_upload"] = {
            "document_id": created["document_id"],
            "version_id": upload_payload["version_id"],
            "source_pdf": str(pdf_path),
        }

        _, parse_payload = _request(
            "POST",
            _path(args.base_url, f"/api/v1/documents/{created['document_id']}/parse"),
            token=user_token,
            json_payload={"model": defaults["provider_model"]},
        )
        _assert(isinstance(parse_payload, dict), "parse create did not return JSON")
        created["parse_job_id"] = parse_payload["id"]
        parse_result = poll_parse_job(args.base_url, user_token, created["parse_job_id"])
        _assert(parse_result["status"] == "index_ready", f"parse job did not reach index_ready: {parse_result}")
        checks["parse_job"] = {
            "job_id": created["parse_job_id"],
            "status": parse_result["status"],
            "current_step": parse_result["current_step"],
        }

        _, document_payload = _request("GET", _path(args.base_url, f"/api/v1/documents/{created['document_id']}"), token=user_token)
        _assert(isinstance(document_payload, dict), "document detail did not return JSON")
        _assert(document_payload["uploaded_via_kb_id"] == created["knowledge_base_id"], "uploaded_via_kb_id did not persist")
        _assert(document_payload["status"] == "index_ready", "document did not become index_ready")
        checks["document_detail"] = {
            "active_version_id": document_payload["active_version_id"],
            "status": document_payload["status"],
        }

        _, knowledge_base_bound = _request(
            "POST",
            _path(args.base_url, f"/api/v1/workspaces/{created['workspace_id']}/knowledge-bases/{created['knowledge_base_id']}/documents"),
            token=user_token,
            json_payload={"document_id": created["document_id"], "enabled": True, "label": "phase4.7", "sort_order": 0},
        )
        _assert(isinstance(knowledge_base_bound, dict), "knowledge base document bind did not return JSON")
        _assert(any(item["document_id"] == created["document_id"] for item in knowledge_base_bound["documents"]), "document missing from KB after bind")
        checks["knowledge_base_bind_document"] = {"document_count": len(knowledge_base_bound["documents"])}

        _, skill_payload = _request(
            "POST",
            _path(args.base_url, "/api/v1/skills"),
            token=user_token,
            json_payload={
                "name": f"Phase47 Validation Skill {suffix}",
                "description": "Phase 4.7 runtime validation skill",
                "system_prompt": "Answer only from the uploaded document. Keep the answer short and factual.",
                "document_ids": [],
                "knowledge_base_id": created["knowledge_base_id"],
                "provider_id": created["provider_id"],
                "model": defaults["provider_model"],
                "request_config": {"temperature": 0},
                "conversation_config": {},
                "retrieval_config": {"top_k": 4},
                "generation_config": {"temperature": 0},
                "document_scope_type": "explicit",
                "visibility": "private",
            },
        )
        _assert(isinstance(skill_payload, dict), "skill create did not return JSON")
        created["skill_id"] = skill_payload["id"]
        _assert(skill_payload["knowledge_base_id"] == created["knowledge_base_id"], "skill did not keep KB binding")
        checks["skill_create"] = {"skill_id": created["skill_id"]}

        _, session_payload = _request(
            "POST",
            _path(args.base_url, "/api/v1/chat/sessions"),
            token=user_token,
            json_payload={"title": "Phase4.7 Validation Session", "skill_id": created["skill_id"]},
        )
        _assert(isinstance(session_payload, dict), "chat session create did not return JSON")
        created["session_id"] = session_payload["id"]
        checks["session_create"] = {"session_id": created["session_id"]}

        _, direct_run = _request(
            "POST",
            _path(args.base_url, "/api/v1/chat/ask"),
            token=user_token,
            json_payload={
                "question": DEFAULT_DIRECT_QUESTION,
                "document_id": created["document_id"],
                "model": defaults["provider_model"],
                "provider_id": created["provider_id"],
                "session_id": created["session_id"],
                "retrieval_config": {"top_k": 3},
                "generation_config": {"temperature": 0},
            },
        )
        _assert(isinstance(direct_run, dict), "direct run did not return JSON")
        created["direct_run_id"] = direct_run["id"]
        _assert(direct_run["status"] == "completed", f"direct run not completed: {direct_run['status']}")
        _assert(bool(direct_run.get("answer_text") or direct_run.get("answer")), "direct run answer is empty")
        checks["direct_query"] = {
            "run_id": created["direct_run_id"],
            "status": direct_run["status"],
            "citation_count": len(direct_run.get("citations", [])),
        }

        _, skill_run = _request(
            "POST",
            _path(args.base_url, f"/api/v1/chat/skills/{created['skill_id']}/run"),
            token=user_token,
            json_payload={
                "question": DEFAULT_SKILL_QUESTION,
                "document_id": created["document_id"],
                "provider_id": created["provider_id"],
                "session_id": created["session_id"],
                "generation_config": {"temperature": 0},
            },
        )
        _assert(isinstance(skill_run, dict), "skill run did not return JSON")
        created["skill_run_id"] = skill_run["id"]
        _assert(skill_run["status"] == "completed", f"skill run not completed: {skill_run['status']}")
        _assert(bool(skill_run.get("answer_text") or skill_run.get("answer")), "skill run answer is empty")
        checks["skill_run"] = {
            "run_id": created["skill_run_id"],
            "status": skill_run["status"],
            "citation_count": len(skill_run.get("citations", [])),
        }

        _, messages_payload = _request(
            "GET",
            _path(args.base_url, f"/api/v1/chat/sessions/{created['session_id']}/messages"),
            token=user_token,
        )
        _assert(isinstance(messages_payload, list), "session messages did not return list")
        _assert(len(messages_payload) >= 4, "session does not contain expected user/assistant pairs")
        checks["session_messages"] = {"count": len(messages_payload)}

        switched_default_again = switch_context(args.base_url, user_token, default_workspace_id)
        status_workspace_isolation, workspace_isolation_payload = _request(
            "GET",
            _path(args.base_url, f"/api/v1/documents/{created['document_id']}"),
            token=switched_default_again["access_token"],
            expected_status=404,
        )
        _assert(status_workspace_isolation == 404, "workspace isolation negative path did not return 404")
        checks["workspace_isolation_negative"] = {
            "status": status_workspace_isolation,
            "detail": workspace_isolation_payload,
        }
        switched_validation_again = switch_context(args.base_url, switched_default_again["access_token"], created["workspace_id"])
        user_token = switched_validation_again["access_token"]

        _, user_portrait = _request(
            "GET",
            _path(args.base_url, f"/api/v1/platform/users/{created['user_id']}/access-portrait"),
            token=admin_token,
        )
        _assert(isinstance(user_portrait, dict), "user portrait did not return JSON")
        _assert(user_portrait["user"]["id"] == created["user_id"], "user portrait returned wrong user")
        checks["platform_user_portrait"] = {
            "resolved_workspace_id": user_portrait["effective_portrait"]["resolved_context"]["workspace_id"],
            "denied_reason_count": len(user_portrait["effective_portrait"]["explainability"]["denied_reasons"]),
        }

        _, workspace_portrait = _request(
            "GET",
            _path(args.base_url, f"/api/v1/platform/workspaces/{created['workspace_id']}/access-portrait"),
            token=admin_token,
        )
        _assert(isinstance(workspace_portrait, dict), "workspace portrait did not return JSON")
        _assert(workspace_portrait["workspace"]["id"] == created["workspace_id"], "workspace portrait returned wrong workspace")
        checks["platform_workspace_portrait"] = {
            "active_founder_invariant_ok": workspace_portrait["membership_summary"]["active_founder_invariant_ok"],
            "pending_invites": workspace_portrait["invite_summary"]["pending"],
        }

        _, tenants_payload = _request("GET", _path(args.base_url, "/api/v1/platform/tenants"), token=admin_token)
        _assert(isinstance(tenants_payload, list) and len(tenants_payload) >= 1, "platform tenant list is empty")
        _, users_payload = _request("GET", _path(args.base_url, "/api/v1/platform/users"), token=admin_token)
        _assert(isinstance(users_payload, list), "platform user list did not return list")
        checks["platform_directory"] = {
            "tenant_count": len(tenants_payload),
            "user_count": len(users_payload),
        }

        if args.cleanup:
            cleanup = cleanup_success(args.base_url, admin_token, user_token, created)
        else:
            cleanup = {
                "status": "skipped_by_flag",
                "retained_for_failure_analysis": False,
                "remaining_artifacts": [value for value in created.values() if value],
            }

        return {
            "summary": {
                "status": "passed",
                "phase_gate": "Phase 4.7 baseline",
                "base_url": args.base_url,
                "started_at": args.started_at,
                "finished_at": _utcnow(),
                "source_pdf": str(pdf_path),
                "admin_user": admin_user["username"],
            },
            "created": created,
            "checks": checks,
            "cleanup": cleanup,
            "unverified_checks": {
                "cross_tenant_negative_runtime": "not executed by default; tenant creation is not a first-class operator flow in Phase 4.x",
            },
        }
    except Exception as exc:
        raise ValidationFailure(str(exc), created=created, checks=checks, cleanup=cleanup) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 4.7 runtime validation against the live PageIndex backend.")
    parser.add_argument("--base-url", default=os.environ.get("PAGEINDEX_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--admin-username", default=os.environ.get("PAGEINDEX_ADMIN_USERNAME", "admin"))
    parser.add_argument("--admin-password", default=os.environ.get("PAGEINDEX_ADMIN_PASSWORD", "changeme"))
    parser.add_argument("--pdf", default=os.environ.get("PAGEINDEX_VALIDATION_PDF", str(DEFAULT_PDF)))
    parser.add_argument("--output", default=os.environ.get("PAGEINDEX_VALIDATION_OUTPUT", str(DEFAULT_OUTPUT)))
    parser.add_argument("--exercise-password-reset", action="store_true")
    parser.add_argument("--no-cleanup", dest="cleanup", action="store_false")
    parser.set_defaults(cleanup=True)
    args = parser.parse_args()
    args.started_at = _utcnow()
    return args


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = run_validation(args)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        print(f"wrote validation artifact: {output_path}")
        return 0
    except ValidationFailure as exc:
        failure = {
            "summary": {
                "status": "failed",
                "phase_gate": "Phase 4.7 baseline",
                "base_url": args.base_url,
                "started_at": args.started_at,
                "finished_at": _utcnow(),
            },
            "created": exc.created,
            "checks": exc.checks,
            "error": {
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
            "cleanup": {
                "status": "skipped_due_to_failure",
                "retained_for_failure_analysis": True,
                "remaining_artifacts": [value for value in exc.created.values() if value],
                "last_known_cleanup": exc.cleanup,
            },
        }
        output_path.write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(failure["summary"], ensure_ascii=False, indent=2))
        print(str(exc), file=sys.stderr)
        print(f"wrote failure artifact: {output_path}", file=sys.stderr)
        return 1
    except Exception as exc:
        failure = {
            "summary": {
                "status": "failed",
                "phase_gate": "Phase 4.7 baseline",
                "base_url": args.base_url,
                "started_at": args.started_at,
                "finished_at": _utcnow(),
            },
            "created": {},
            "checks": {},
            "error": {
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
            "cleanup": {
                "status": "skipped_due_to_failure",
                "retained_for_failure_analysis": True,
                "remaining_artifacts": [],
            },
        }
        output_path.write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(failure["summary"], ensure_ascii=False, indent=2))
        print(str(exc), file=sys.stderr)
        print(f"wrote failure artifact: {output_path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
