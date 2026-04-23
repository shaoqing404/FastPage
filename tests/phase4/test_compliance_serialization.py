import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.models.compliance import ComplianceRun
from app.services.compliance_service import serialize_compliance_run


class TestComplianceSerialization(unittest.TestCase):
    def test_serialize_compliance_run_converts_timestamps_to_iso_strings(self):
        created_at = datetime(2026, 4, 22, 16, 0, 0)
        started_at = datetime(2026, 4, 22, 16, 0, 1)
        finished_at = datetime(2026, 4, 22, 16, 0, 2)
        run = ComplianceRun(
            id="run_1",
            tenant_id="tenant_1",
            workspace_id="ws_1",
            user_id="user_1",
            knowledge_base_id="kb_1",
            model="openai/qwen3.6-plus",
            status="completed",
            mode="multi_manual_federated",
            question="航空公司特殊机场相关要求是否在手册中有明确依据",
            facts_json="{}",
            verdict_policy_json="{}",
            output_config_json="{}",
            retrieval_config_json="{}",
            generation_config_json="{}",
            citations_json="[]",
            evidence_json="[]",
            gaps_json="[]",
            conflicts_json="[]",
            execution_context_json="{}",
            metrics_json="{}",
            created_at=created_at,
            started_at=started_at,
            finished_at=finished_at,
        )

        payload = serialize_compliance_run(run)

        self.assertEqual(payload["created_at"], created_at.isoformat())
        self.assertEqual(payload["started_at"], started_at.isoformat())
        self.assertEqual(payload["finished_at"], finished_at.isoformat())


if __name__ == "__main__":
    unittest.main()
