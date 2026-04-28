import os
import sys
import unittest
import json
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

from app.services.runtime_observation_service import OBSERVATION_PAYLOAD_JSON_MAX_BYTES, sanitize_observation_payload, serialize_observation_payload_for_storage
from app.models import ChatRun
from app.services.chat_service import serialize_run_observation_payload


class TestRuntimeObservationSerialization(unittest.TestCase):
    def test_sanitize_observation_payload_encodes_nested_datetimes(self):
        created_at = datetime(2026, 4, 22, 16, 8, 34)

        payload = sanitize_observation_payload(
            {
                "created_at": created_at,
                "nested": {
                    "finished_at": created_at,
                },
            }
        )

        self.assertEqual(payload["created_at"], created_at.isoformat())
        self.assertEqual(payload["nested"]["finished_at"], created_at.isoformat())

    def test_observation_payload_storage_compacts_oversized_payload(self):
        payload_json = serialize_observation_payload_for_storage(
            {
                "id": "run_1",
                "answer": "长答案" * 50000,
                "selected_sections": [{"section_text": "正文" * 50000}],
            }
        )

        self.assertLessEqual(len(payload_json.encode("utf-8")), OBSERVATION_PAYLOAD_JSON_MAX_BYTES)
        self.assertIn('"payload_truncated": true', payload_json)

    def test_chat_run_completed_observation_keeps_only_run_summary_and_node_ids(self):
        created_at = datetime(2026, 4, 27, 9, 52, 9)
        run = ChatRun(
            id="run_1",
            tenant_id="tenant_1",
            workspace_id="ws_1",
            user_id="user_1",
            session_id="session_1",
            document_id="doc_1",
            version_id="ver_1",
            skill_id="skill_1",
            provider_id="provider_1",
            model="model_1",
            question="同一航班上，无成人陪伴儿童最多可承运几名？",
            answer="无成人陪伴儿童最多 10 个。",
            answer_text="无成人陪伴儿童最多 10 个。",
            answer_with_marker="无成人陪伴儿童最多 10 个。[cit_1]",
            status="completed",
            request_config_json="{}",
            conversation_config_json="{}",
            retrieval_config_json='{"retrieval_mode":"fast","node_top_k":10}',
            generation_config_json="{}",
            selected_sections_json=json.dumps(
                [
                    {
                        "document_id": "doc_1",
                        "version_id": "ver_1",
                        "node_id": "0195",
                        "title": "11.2 旅客运输标准和要求",
                        "page_start": 933,
                        "page_end": 950,
                        "section_text": "正文" * 10000,
                    }
                ],
                ensure_ascii=False,
            ),
            citations_json=json.dumps(
                [
                    {
                        "document_id": "doc_1",
                        "version_id": "ver_1",
                        "node_id": "0195",
                        "title": "11.2 旅客运输标准和要求",
                        "page_start": 933,
                        "page_end": 950,
                    }
                ],
                ensure_ascii=False,
            ),
            execution_context_json=json.dumps(
                {
                    "retrieval": {
                        "retrieval_mode": "fast",
                        "node_top_k": 10,
                        "selected_node_count": 1,
                        "diagnostics": {
                            "fast": {
                                "selected_nodes": [
                                    {
                                        "document_id": "doc_1",
                                        "version_id": "ver_1",
                                        "node_id": "0195",
                                        "title": "11.2 旅客运输标准和要求",
                                        "page_start": 933,
                                        "page_end": 950,
                                        "section_text": "正文" * 10000,
                                    }
                                ]
                            }
                        },
                    }
                },
                ensure_ascii=False,
            ),
            metrics_json='{"retrieval_mode":"fast","node_top_k":10,"selected_node_count":1,"total_ms":100}',
            created_at=created_at,
            started_at=created_at,
            finished_at=created_at,
        )

        payload = serialize_run_observation_payload(run)
        payload_text = json.dumps(payload, ensure_ascii=False)

        self.assertEqual(payload["schema_version"], "chat_run_completed_observation_v1")
        self.assertEqual(payload["retrieval"]["retrieval_mode"], "fast")
        self.assertEqual(payload["pageindex_nodes"]["items"][0]["node_id"], "0195")
        self.assertNotIn("execution_context", payload)
        self.assertNotIn("selected_sections", payload)
        self.assertNotIn("answer_with_marker", payload)
        self.assertNotIn("section_text", payload_text)


if __name__ == "__main__":
    unittest.main()
