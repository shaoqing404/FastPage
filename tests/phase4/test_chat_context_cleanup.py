import asyncio
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("litellm", MagicMock())

from app.core.principal import Principal
from app.models import Document, DocumentVersion, User
from app.services.chat_service import _create_pending_run, create_chat_run


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


if __name__ == "__main__":
    unittest.main()
