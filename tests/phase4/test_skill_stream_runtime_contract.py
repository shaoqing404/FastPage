import asyncio
import importlib.util
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.core.principal import Principal
from app.services.chat_service import _build_execution_context, stream_skill_run_events


CHAT_ROUTER_MODULE_NAME = "phase48_chat_router_under_test"
CHAT_ROUTER_PATH = Path(__file__).resolve().parents[2] / "app" / "api" / "routers" / "chat.py"


class TestSkillStreamRuntimeContract(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id="user_1", tenant_id="tenant_1")
        self.principal = Principal(
            kind="session",
            tenant_id="tenant_1",
            workspace_id="ws_1",
            tenant_membership_role="admin",
            tenant_membership_status="active",
            workspace_membership_role="admin",
            workspace_membership_status="active",
            workspace_permissions={"can_run_skills": True, "can_view_runs": True},
            user=self.user,
        )
        self.skill = SimpleNamespace(
            id="skill_1",
            name="Demo Skill",
            model="openai/saved-model",
            request_config_json="{}",
            conversation_config_json="{}",
            retrieval_config_json="{}",
            generation_config_json="{}",
            documents=[SimpleNamespace(document_id="doc_1")],
        )
        self.document = SimpleNamespace(id="doc_1", workspace_id="ws_1")
        self.version = SimpleNamespace(id="ver_1", parsed_structure_path="/tmp/parsed.json", parse_status="index_ready")

    @patch("app.services.chat_service._create_pending_run")
    def test_stream_skill_run_events_accepts_explicit_model(self, mock_create_pending_run):
        created_run = SimpleNamespace(
            id="run_1",
            tenant_id="tenant_1",
            session_id="session_1",
            created_at=datetime(2026, 4, 21, 10, 0, 0),
        )
        mock_create_pending_run.return_value = created_run

        async def scenario():
            stream = stream_skill_run_events(
                MagicMock(),
                principal=self.principal,
                user=self.user,
                skill=self.skill,
                document=self.document,
                version=self.version,
                question="hello",
                model="openai/draft-model",
                request_config={},
                conversation_config={},
                retrieval_config={},
                generation_config={},
            )
            return await anext(stream)

        first_event = asyncio.run(scenario())

        self.assertEqual(first_event["event"], "run_started")
        _, kwargs = mock_create_pending_run.call_args
        self.assertEqual(kwargs["model"], "openai/draft-model")

    def test_stream_route_emits_error_event_when_stream_setup_fails(self):
        chat_router_spec = importlib.util.spec_from_file_location(CHAT_ROUTER_MODULE_NAME, CHAT_ROUTER_PATH)
        chat_router_module = importlib.util.module_from_spec(chat_router_spec)
        assert chat_router_spec is not None and chat_router_spec.loader is not None
        sys.modules[CHAT_ROUTER_MODULE_NAME] = chat_router_module
        chat_router_spec.loader.exec_module(chat_router_module)

        app = FastAPI()
        app.include_router(chat_router_module.router)
        app.dependency_overrides[chat_router_module.get_current_principal] = lambda: self.principal
        app.dependency_overrides[chat_router_module.get_db] = lambda: MagicMock()
        chat_router_module._require_can_run_skills = lambda principal: None
        chat_router_module.get_skill_or_404 = lambda db, principal, skill_id: self.skill
        chat_router_module.resolve_document_version = lambda db, principal, document_id, version_id: (self.document, self.version)

        async def broken_stream_skill_run_events(*args, **kwargs):
            if False:
                yield None
            raise RuntimeError("boom-before-run")

        chat_router_module.stream_skill_run_events = broken_stream_skill_run_events

        client = TestClient(app, raise_server_exceptions=False)
        with client.stream(
            "POST",
            "/api/v1/chat/skills/skill_1/run",
            json={"question": "hello", "stream": True},
        ) as response:
            body = b"".join(response.iter_raw()).decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: error", body)
        self.assertIn("boom-before-run", body)

    def test_build_execution_context_preserves_retrieval_diagnostics(self):
        execution_context = _build_execution_context(
            provider_config={
                "provider_id": "provider_1",
                "name": "Provider",
                "provider_type": "openai",
                "scope": "workspace",
                "resolution_source": "workspace",
            },
            resolved_model="openai/test-model",
            conversation_config={},
            history_info={
                "used": False,
                "history_messages_used": 0,
                "history_turns_used": 0,
                "history_token_estimate": 0,
            },
            retrieval_info={
                "diagnostics": {
                    "outline": {
                        "manuals": [
                            {
                                "document_id": "doc_1",
                                "selected_node_ids": ["0001"],
                            }
                        ],
                    },
                    "rerank": {
                        "meta": {"applied": False, "mode": "round_robin_manual_merge"},
                        "repair": {},
                    },
                },
                "outline_selection_strategy": "outline_llm",
                "documents_considered": 1,
            },
            generation_info={"temperature": 0},
        )

        self.assertEqual(
            execution_context["retrieval"]["diagnostics"]["outline"]["manuals"][0]["selected_node_ids"],
            ["0001"],
        )
        self.assertFalse(execution_context["retrieval"]["diagnostics"]["rerank"]["meta"]["applied"])


if __name__ == "__main__":
    unittest.main()
