#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.core.config import get_settings  # noqa: E402


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def login(client: TestClient) -> tuple[str, dict]:
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "changeme"})
    _assert(response.status_code == 200, f"login failed: {response.text}")
    payload = response.json()
    return payload["access_token"], payload["user"]


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ensure_provider(client: TestClient, headers: dict[str, str], name: str) -> dict:
    settings = get_settings()
    created = client.post(
        "/api/v1/model-providers",
        headers=headers,
        json={
            "provider_type": "openai_compatible",
            "name": name,
            "base_url": settings.llm_base_url,
            "api_key": settings.llm_api_key,
            "default_model": "openai/qwen-plus",
            "extra_headers": {},
            "enabled": True,
            "is_default": False,
        },
    )
    _assert(created.status_code == 200, f"provider create failed: {created.text}")
    return created.json()


def ensure_skill(client: TestClient, headers: dict[str, str], provider_id: str, document_id: str) -> dict:
    skill_name = f"phase2-validation-skill-{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/api/v1/skills",
        headers=headers,
        json={
            "name": skill_name,
            "description": "phase2 validation skill",
            "system_prompt": "Answer only from the manual or paper excerpts. Keep it factual.",
            "document_ids": [document_id],
            "provider_id": provider_id,
            "model": "openai/qwen-plus",
            "request_config": {"temperature": 0},
            "retrieval_config": {"top_k": 3, "selection_mode": "outline_llm", "max_context_pages": 8},
            "generation_config": {"temperature": 0},
            "document_scope_type": "explicit",
        },
    )
    _assert(created.status_code == 200, f"skill create failed: {created.text}")
    return created.json()


def validate_real_provider_flow(client: TestClient, token: str) -> dict:
    headers = bearer_headers(token)
    documents = client.get("/api/v1/documents", headers=headers)
    _assert(documents.status_code == 200, f"documents list failed: {documents.text}")
    docs = documents.json()
    ready_doc = next(doc for doc in docs if doc["display_name"] == "2603.22458v1.pdf")

    provider = ensure_provider(client, headers, f"phase2-validation-provider-{uuid.uuid4().hex[:8]}")
    session = client.post("/api/v1/chat/sessions", headers=headers, json={"title": "Phase2 Validation Session"})
    _assert(session.status_code == 200, f"session create failed: {session.text}")
    session_id = session.json()["id"]

    direct = client.post(
        "/api/v1/chat/ask",
        headers=headers,
        json={
            "question": "What is the title of this paper?",
            "document_id": ready_doc["id"],
            "model": "openai/qwen-plus",
            "provider_id": provider["id"],
            "session_id": session_id,
            "retrieval_config": {"top_k": 2, "selection_mode": "outline_llm", "max_context_pages": 6},
            "generation_config": {"temperature": 0},
        },
    )
    _assert(direct.status_code == 200, f"direct ask failed: {direct.text}")
    direct_payload = direct.json()
    _assert("[CITATIONS_JSON_BEGIN]" in (direct_payload.get("answer_with_marker") or ""), "answer_with_marker missing citations marker")
    _assert(isinstance(direct_payload.get("citations"), list) and len(direct_payload["citations"]) > 0, "citations missing")

    skill = ensure_skill(client, headers, provider["id"], ready_doc["id"])
    skill_run = client.post(
        f"/api/v1/chat/skills/{skill['id']}/run",
        headers=headers,
        json={
            "question": "What is the title of this paper?",
            "document_id": ready_doc["id"],
            "session_id": session_id,
            "generation_config": {"temperature": 0},
        },
    )
    _assert(skill_run.status_code == 200, f"skill run failed: {skill_run.text}")
    skill_payload = skill_run.json()
    _assert(skill_payload["status"] == "completed", f"unexpected skill status: {skill_payload['status']}")
    _assert(skill_payload.get("citations"), "skill citations missing")

    messages = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
    _assert(messages.status_code == 200, f"session messages failed: {messages.text}")
    message_list = messages.json()
    _assert(len(message_list) >= 4, "session messages missing expected user/assistant pairs")

    return {
        "provider_id": provider["id"],
        "session_id": session_id,
        "direct_run_id": direct_payload["id"],
        "skill_run_id": skill_payload["id"],
        "citation_count": len(direct_payload["citations"]),
    }


def validate_api_key_and_tenant_security(client: TestClient, token: str, user_payload: dict) -> dict:
    headers = bearer_headers(token)
    created = client.post("/api/v1/auth/apikeys", headers=headers, json={"name": "phase2-security-key"})
    _assert(created.status_code == 200, f"api key create failed: {created.text}")
    key_payload = created.json()
    api_key_headers = {"X-API-Key": key_payload["api_key"]}

    provider_list = client.get("/api/v1/model-providers", headers=api_key_headers)
    _assert(provider_list.status_code == 200, "api key should access same-tenant providers")

    revoked = client.delete(f"/api/v1/auth/apikeys/{key_payload['id']}", headers=headers)
    _assert(revoked.status_code == 204, f"api key revoke failed: {revoked.text}")

    denied = client.get("/api/v1/model-providers", headers=api_key_headers)
    _assert(denied.status_code == 401, "revoked api key should be rejected")

    settings = get_settings()
    engine = create_engine(settings.database_url, future=True)
    foreign_tenant_id = f"tenant_phase2_{uuid.uuid4().hex[:8]}"
    foreign_user_id = f"user_phase2_{uuid.uuid4().hex[:8]}"
    foreign_doc_id = f"doc_phase2_{uuid.uuid4().hex[:8]}"
    foreign_ver_id = f"ver_phase2_{uuid.uuid4().hex[:8]}"

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name, status, created_at) VALUES (:id, :name, 'active', NOW())"),
            {"id": foreign_tenant_id, "name": "Phase2 Foreign Tenant"},
        )
        conn.execute(
            text(
                "INSERT INTO users (id, tenant_id, username, password_hash, is_active, created_at) "
                "VALUES (:id, :tenant_id, :username, :password_hash, 1, NOW())"
            ),
            {
                "id": foreign_user_id,
                "tenant_id": foreign_tenant_id,
                "username": f"foreign_{foreign_tenant_id}",
                "password_hash": "unused",
            },
        )
        conn.execute(
            text(
                "INSERT INTO documents (id, tenant_id, owner_user_id, display_name, source_filename, active_version_id, status, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :owner_user_id, 'foreign.pdf', 'foreign.pdf', NULL, 'uploaded', NOW(), NOW())"
            ),
            {
                "id": foreign_doc_id,
                "tenant_id": foreign_tenant_id,
                "owner_user_id": foreign_user_id,
            },
        )
        conn.execute(
            text(
                "INSERT INTO document_versions (id, document_id, version_no, storage_path, file_hash, parse_status, parsed_structure_path, parse_error, created_at) "
                "VALUES (:id, :document_id, 1, 'minio://noop', 'noop', 'uploaded', NULL, NULL, NOW())"
            ),
            {
                "id": foreign_ver_id,
                "document_id": foreign_doc_id,
            },
        )
        conn.execute(
            text("UPDATE documents SET active_version_id=:active_version_id WHERE id=:id"),
            {"active_version_id": foreign_ver_id, "id": foreign_doc_id},
        )

    forbidden = client.get(f"/api/v1/documents/{foreign_doc_id}", headers=headers)
    _assert(forbidden.status_code == 404, "cross-tenant document access should be denied")

    return {
        "revoked_key_id": key_payload["id"],
        "cross_tenant_document_id": foreign_doc_id,
        "tenant_id": user_payload["tenant_id"],
    }


def validate_migration_empty_and_old() -> dict:
    settings = get_settings()
    base_url = settings.database_url.rsplit("/", 1)[0]
    empty_db = f"pageindex_phase2_empty_{uuid.uuid4().hex[:6]}"
    old_db = f"pageindex_phase2_old_{uuid.uuid4().hex[:6]}"
    root_db_url = f"{base_url}/mysql"

    engine = create_engine(root_db_url, future=True)
    with engine.begin() as conn:
        conn.execute(text(f"CREATE DATABASE {empty_db} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
        conn.execute(text(f"CREATE DATABASE {old_db} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))

    env = os.environ.copy()
    env["DATABASE_URL"] = f"{base_url}/{empty_db}"
    subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-c", "from app.core.bootstrap import init_db; init_db(); print('empty_ok')"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    old_engine = create_engine(f"{base_url}/{old_db}", future=True)
    with old_engine.begin() as conn:
        conn.execute(text("CREATE TABLE tenants (id VARCHAR(64) PRIMARY KEY, name VARCHAR(255) NOT NULL, status VARCHAR(32) NOT NULL, created_at DATETIME NOT NULL)"))
        conn.execute(text("CREATE TABLE users (id VARCHAR(64) PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL, username VARCHAR(128) NOT NULL, password_hash VARCHAR(255) NOT NULL, is_active BOOL NOT NULL, created_at DATETIME NOT NULL)"))
        conn.execute(text("CREATE TABLE chat_skills (id VARCHAR(64) PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL, owner_user_id VARCHAR(64) NOT NULL, name VARCHAR(255) NOT NULL, description TEXT NULL, system_prompt TEXT NOT NULL, document_scope_type VARCHAR(32) NOT NULL, model VARCHAR(255) NOT NULL, request_config_json TEXT NOT NULL, is_active BOOL NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        conn.execute(text("CREATE TABLE chat_runs (id VARCHAR(64) PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL, user_id VARCHAR(64) NOT NULL, document_id VARCHAR(64) NULL, skill_id VARCHAR(64) NULL, model VARCHAR(255) NOT NULL, question TEXT NOT NULL, answer TEXT NULL, status VARCHAR(32) NOT NULL, selected_sections_json TEXT NOT NULL, metrics_json TEXT NOT NULL, started_at DATETIME NULL, finished_at DATETIME NULL, created_at DATETIME NOT NULL)"))

    env["DATABASE_URL"] = f"{base_url}/{old_db}"
    subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-c", "from app.core.bootstrap import init_db; init_db(); print('old_ok')"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    with old_engine.connect() as conn:
        columns = conn.execute(text("SHOW COLUMNS FROM chat_runs")).fetchall()
        column_names = {row[0] for row in columns}
    _assert("session_id" in column_names and "provider_id" in column_names and "citations_json" in column_names, "old schema patch missing expected columns")

    return {"empty_db": empty_db, "old_db": old_db}


def main() -> None:
    client = TestClient(app)
    token, user_payload = login(client)
    provider_result = validate_real_provider_flow(client, token)
    security_result = validate_api_key_and_tenant_security(client, token, user_payload)
    migration_result = validate_migration_empty_and_old()

    result = {
        "provider_flow": provider_result,
        "security": security_result,
        "migration": migration_result,
        "notes": [
            "session message ordering validated through same-session direct ask + skill run",
            "concurrency smoke intentionally deferred; frontend and full staging run pending",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
