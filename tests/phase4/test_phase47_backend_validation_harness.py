import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from spec.fastapi_service.phase4_access_and_admin_control_plane import phase4_7_backend_validation as validation


class TestPhase47BackendValidationHarness(unittest.TestCase):
    def test_run_validation_keeps_direct_ask_stateless_and_reuses_skill_session_for_chat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "validation.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n% phase47 test pdf\n")

            args = SimpleNamespace(
                base_url="http://127.0.0.1:22223",
                admin_username="admin",
                admin_password="changeme",
                pdf=str(pdf_path),
                output=str(Path(tmpdir) / "result.json"),
                exercise_password_reset=False,
                cleanup=True,
                started_at="2026-04-17T00:00:00+00:00",
            )

            calls = {"direct_ask": 0, "skill_run": 0}

            def fake_login(base_url: str, username: str, password: str) -> dict:
                if username == "admin":
                    return {
                        "access_token": "admin-token",
                        "user": {"id": "admin-user", "username": "admin"},
                    }
                return {
                    "access_token": "user-default-token",
                    "user": {"id": "user_1"},
                    "workspace": {"id": "ws_default"},
                }

            def fake_switch_context(base_url: str, token: str, workspace_id: str) -> dict:
                return {
                    "access_token": f"token-for-{workspace_id}",
                    "workspace": {"id": workspace_id},
                }

            def fake_request(
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
                if url.endswith("/api/v1/platform/users") and method == "POST":
                    return 201, {"id": "user_1", "email": "phase47@example.test"}
                if url.endswith("/api/v1/workspaces") and method == "GET":
                    return 200, [{"id": "ws_default"}, {"id": "ws_validation"}]
                if url.endswith("/api/v1/workspaces") and method == "POST":
                    return 201, {
                        "access_token": "token-for-ws_validation",
                        "workspace": {"id": "ws_validation"},
                        "workspace_membership": {"role": "founder"},
                    }
                if url.endswith("/api/v1/auth/apikeys") and method == "POST":
                    return 200, {"id": "api_key_1", "api_key": "phase47-key"}
                if url.endswith("/api/v1/platform/users") and method == "GET" and api_key:
                    return 403, {"detail": "Platform admin session required"}
                if url.endswith("/access-portrait") and method == "GET" and api_key:
                    return 403, {"detail": "Platform admin session required"}
                if url.endswith("/knowledge-bases") and method == "POST":
                    return 200, {"id": "kb_1"}
                if url.endswith("/api/v1/model-providers") and method == "POST":
                    return 200, {"id": "provider_1"}
                if url.endswith("/probe-models") and method == "POST":
                    return 200, {"id": "provider_1", "default_model": "openai/qwen-plus", "supported_models": ["openai/qwen-plus"]}
                if url.endswith("/api/v1/documents/upload") and method == "POST":
                    self.assertIsNotNone(body)
                    self.assertIsNotNone(content_type)
                    return 200, {"document_id": "doc_1", "version_id": "ver_1"}
                if url.endswith("/api/v1/documents/doc_1/parse") and method == "POST":
                    return 200, {"id": "job_1"}
                if url.endswith("/api/v1/documents/doc_1") and method == "GET" and token == "token-for-ws_validation":
                    return 200, {"id": "doc_1", "uploaded_via_kb_id": "kb_1", "status": "index_ready", "active_version_id": "ver_1"}
                if url.endswith("/knowledge-bases/kb_1/documents") and method == "POST":
                    return 200, {"documents": [{"document_id": "doc_1"}]}
                if url.endswith("/api/v1/skills") and method == "POST":
                    return 200, {"id": "skill_1", "knowledge_base_id": "kb_1"}
                if url.endswith("/api/v1/chat/ask") and method == "POST":
                    calls["direct_ask"] += 1
                    self.assertIsNotNone(json_payload)
                    self.assertNotIn("session_id", json_payload)
                    return 200, {"id": "run_direct_1", "status": "completed", "answer_text": "direct answer", "citations": [], "session_id": None}
                if url.endswith("/api/v1/chat/skills/skill_1/run") and method == "POST":
                    calls["skill_run"] += 1
                    self.assertIsNotNone(json_payload)
                    if calls["skill_run"] == 1:
                        self.assertTrue(json_payload.get("auto_create_session"))
                        self.assertNotIn("session_id", json_payload)
                        return 200, {
                            "id": "run_skill_1",
                            "status": "completed",
                            "answer_text": "skill answer",
                            "citations": [{"id": "c1"}],
                            "session_id": "sess_1",
                        }
                    self.assertEqual(json_payload.get("session_id"), "sess_1")
                    return 200, {
                        "id": "run_skill_2",
                        "status": "completed",
                        "answer_text": "skill follow-up",
                        "citations": [{"id": "c2"}],
                        "session_id": "sess_1",
                    }
                if url.endswith("/api/v1/chat/skills/skill_1/sessions/sess_1/messages") and method == "GET":
                    return 200, [
                        {"role": "user"},
                        {"role": "assistant"},
                        {"role": "user"},
                        {"role": "assistant"},
                    ]
                if url.endswith("/api/v1/documents/not-a-real-doc") and method == "GET":
                    return 404, {"detail": "Document not found"}
                if url.endswith("/api/v1/documents/doc_1") and method == "GET" and token == "token-for-ws_default":
                    return 404, {"detail": "Document not found"}
                if url.endswith("/api/v1/platform/users/user_1/access-portrait") and method == "GET" and token == "admin-token":
                    return 200, {
                        "user": {"id": "user_1"},
                        "effective_portrait": {
                            "resolved_context": {"workspace_id": "ws_validation"},
                            "explainability": {"denied_reasons": []},
                        },
                    }
                if url.endswith("/api/v1/platform/workspaces/ws_validation/access-portrait") and method == "GET" and token == "admin-token":
                    return 200, {
                        "workspace": {"id": "ws_validation"},
                        "membership_summary": {"active_founder_invariant_ok": True},
                        "invite_summary": {"pending": 0},
                    }
                if url.endswith("/api/v1/platform/tenants") and method == "GET":
                    return 200, [{"id": "tenant_1"}]
                if url.endswith("/api/v1/platform/users") and method == "GET" and token == "admin-token":
                    return 200, [{"id": "user_1"}]
                self.fail(f"Unexpected request: {method} {url} token={token} api_key={api_key} payload={json_payload}")

            with (
                patch.object(validation, "load_runtime_defaults", return_value={
                    "provider_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "provider_api_key": "phase47-test-key",
                    "provider_model": "openai/qwen-plus",
                }),
                patch.object(validation, "login", side_effect=fake_login),
                patch.object(validation, "switch_context", side_effect=fake_switch_context),
                patch.object(validation, "poll_parse_job", return_value={"status": "index_ready", "current_step": "done"}),
                patch.object(validation, "cleanup_success", return_value={
                    "status": "completed",
                    "retained_for_failure_analysis": False,
                    "remaining_artifacts": [],
                }),
                patch.object(validation, "_request", side_effect=fake_request),
            ):
                result = validation.run_validation(args)

        self.assertEqual(result["summary"]["status"], "passed")
        self.assertEqual(result["checks"]["direct_query"]["session_id"], None)
        self.assertEqual(result["created"]["session_id"], "sess_1")
        self.assertEqual(result["checks"]["skill_run"]["session_id"], "sess_1")
        self.assertEqual(result["checks"]["skill_run_followup"]["session_id"], "sess_1")
        self.assertEqual(result["checks"]["session_messages"]["user_messages"], 2)
        self.assertEqual(result["checks"]["session_messages"]["assistant_messages"], 2)
        self.assertEqual(calls, {"direct_ask": 1, "skill_run": 2})
