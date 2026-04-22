import asyncio
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.core.errors import AppError, ErrorCode
from app.core.principal import Principal
from app.models import ChatRun, Document, DocumentVersion, User
from app.services.chat_service import _create_pending_run, create_chat_run, serialize_run, wait_for_chat_run_terminal
from app.services.task_queue_service import close_chat_event_stream, open_chat_event_subscription, publish_chat_event


class TestChatContextCleanup(unittest.TestCase):
    def setUp(self):
        self.user = User(
            id="user_1",
            tenant_id="tenant_legacy",
            username="tester",
            email="tester@example.com",
            is_active=True,
        )
        self.principal = Principal(
            kind="session",
            tenant_id="tenant_target",
            workspace_id="ws_target",
            tenant_membership_role="member",
            tenant_membership_status="active",
            workspace_membership_role="member",
            workspace_membership_status="active",
            workspace_permissions={},
            user=self.user,
        )
        self.document = Document(id="doc_1", tenant_id="tenant_target", workspace_id="ws_target")
        self.version = DocumentVersion(
            id="ver_1",
            document_id="doc_1",
            parse_status="index_ready",
            parsed_structure_path="/tmp/parsed.json",
        )

    @patch("app.services.chat_service.resolve_provider_config")
    @patch("app.services.chat_service._resolve_session_for_run")
    def test_create_pending_run_uses_principal_tenant_for_provider_and_run_scope(
        self,
        mock_resolve_session,
        mock_resolve_provider_config,
    ):
        db = MagicMock()
        mock_resolve_session.return_value = None
        mock_resolve_provider_config.return_value = {
            "provider_id": "provider_1",
            "default_model": "model_1",
        }

        run = _create_pending_run(
            db,
            principal=self.principal,
            user=self.user,
            document=self.document,
            version=self.version,
            question="What changed?",
            model=None,
            request_config={},
        )

        self.assertEqual(run.tenant_id, "tenant_target")
        mock_resolve_provider_config.assert_called_once_with(
            db,
            "tenant_target",
            skill=None,
            explicit_provider_id=None,
            workspace_id="ws_target",
        )

    @patch("app.services.chat_service.resolve_provider_config")
    @patch("app.services.chat_service._resolve_session_for_run")
    def test_create_pending_run_normalizes_openai_compatible_model(
        self,
        mock_resolve_session,
        mock_resolve_provider_config,
    ):
        db = MagicMock()
        mock_resolve_session.return_value = None
        mock_resolve_provider_config.return_value = {
            "provider_id": "provider_1",
            "provider_type": "openai_compatible",
            "default_model": "qwen3.5-plus",
        }

        run = _create_pending_run(
            db,
            principal=self.principal,
            user=self.user,
            document=self.document,
            version=self.version,
            question="What changed?",
            model=None,
            request_config={},
        )

        self.assertEqual(run.model, "openai/qwen3.5-plus")

    @patch("app.services.chat_service.resolve_provider_config")
    @patch("app.services.chat_service._resolve_session_for_run")
    def test_create_pending_run_rejects_unsupported_provider_model_pair(
        self,
        mock_resolve_session,
        mock_resolve_provider_config,
    ):
        db = MagicMock()
        mock_resolve_session.return_value = None
        mock_resolve_provider_config.return_value = {
            "provider_id": "provider_1",
            "provider_type": "openai_compatible",
            "name": "Tenant OpenAI Compatible",
            "default_model": "qwen3-plus",
            "supported_models": ["qwen3-plus", "qwen3.5-plus"],
        }

        with self.assertRaises(AppError) as ctx:
            _create_pending_run(
                db,
                principal=self.principal,
                user=self.user,
                document=self.document,
                version=self.version,
                question="What changed?",
                model="gpt-4o",
                request_config={},
            )

        self.assertEqual(ctx.exception.code, ErrorCode.PROVIDER_MODEL_UNSUPPORTED)

    @patch("app.services.chat_service.wait_for_chat_run_terminal")
    @patch("app.services.chat_service._create_and_enqueue_run")
    def test_create_chat_run_waits_with_principal_tenant(
        self,
        mock_create_and_enqueue_run,
        mock_wait_for_chat_run_terminal,
    ):
        db = MagicMock()
        queued_run = MagicMock(id="run_1")
        mock_create_and_enqueue_run.return_value = queued_run
        mock_wait_for_chat_run_terminal.return_value = queued_run

        run = asyncio.run(
            create_chat_run(
                db,
                principal=self.principal,
                user=self.user,
                document=self.document,
                version=self.version,
                question="What changed?",
                model=None,
                request_config={},
            )
        )

        self.assertIs(run, queued_run)
        _, kwargs = mock_wait_for_chat_run_terminal.call_args
        self.assertEqual(kwargs["tenant_id"], "tenant_target")
        self.assertEqual(kwargs["run_id"], "run_1")

    def test_serialize_run_converts_terminal_timestamps_to_iso_strings(self):
        created_at = datetime(2026, 4, 16, 16, 0, 0)
        started_at = datetime(2026, 4, 16, 16, 0, 1)
        finished_at = datetime(2026, 4, 16, 16, 0, 2)
        run = ChatRun(
            id="run_1",
            tenant_id="tenant_target",
            workspace_id="ws_target",
            user_id="user_1",
            status="completed",
            question="What changed?",
            answer="Done",
            selected_sections_json="[]",
            citations_json="[]",
            execution_context_json="{}",
            metrics_json="{}",
            created_at=created_at,
            started_at=started_at,
            finished_at=finished_at,
        )

        payload = serialize_run(run)

        self.assertEqual(payload["created_at"], created_at.isoformat())
        self.assertEqual(payload["started_at"], started_at.isoformat())
        self.assertEqual(payload["finished_at"], finished_at.isoformat())

    def test_publish_chat_event_serializes_nested_datetimes(self):
        created_at = datetime(2026, 4, 16, 16, 0, 0)

        async def scenario():
            subscription = await open_chat_event_subscription("run_1")
            try:
                await publish_chat_event(
                    "run_1",
                    {
                        "event": "run_completed",
                        "data": {
                            "created_at": created_at,
                            "nested": {
                                "finished_at": created_at,
                            },
                        },
                    },
                )
                event = await subscription.next_event(timeout=0.5)
                self.assertEqual(event["data"]["created_at"], created_at.isoformat())
                self.assertEqual(event["data"]["nested"]["finished_at"], created_at.isoformat())
            finally:
                await close_chat_event_stream("run_1")
                await subscription.close()

        with patch("app.services.task_queue_service.settings.task_queue_backend", "local"):
            asyncio.run(scenario())

    def test_wait_for_chat_run_terminal_refreshes_transaction_before_polling(self):
        class SnapshotStickySession:
            def __init__(self):
                self.rollback_calls = 0

            def rollback(self):
                self.rollback_calls += 1

            def get(self, model, run_id):
                status = "failed" if self.rollback_calls else "queued"
                return ChatRun(
                    id=run_id,
                    tenant_id="tenant_target",
                    workspace_id="ws_target",
                    user_id="user_1",
                    status=status,
                    question="What changed?",
                    model="openai/qwen3.5-plus",
                    selected_sections_json="[]",
                    citations_json="[]",
                    execution_context_json="{}",
                    metrics_json="{}",
                    last_error="Object of type datetime is not JSON serializable" if status == "failed" else None,
                )

        db = SnapshotStickySession()

        run = asyncio.run(
            wait_for_chat_run_terminal(
                db,
                tenant_id="tenant_target",
                run_id="run_1",
                timeout_seconds=0,
            )
        )

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.last_error, "Object of type datetime is not JSON serializable")
        self.assertGreaterEqual(db.rollback_calls, 1)


if __name__ == "__main__":
    unittest.main()
