import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["STORAGE_BACKEND"] = "local"
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.models import DocumentVersion
from app.models.routing_asset_contract import ROUTING_ASSET_SCHEMA_VERSION
from app.services.storage_service import read_document_routing_index


class _LegacyRoutingArtifactBackend:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read_json(self, uri: str) -> dict:
        return self.payload


class TestRoutingAssetContract(unittest.TestCase):
    def test_read_document_routing_index_backfills_v1_contract_defaults(self):
        legacy_payload = {
            "document_label": "Manual Label",
            "source_doc_name": "source.pdf",
            "document_id": "doc_1",
            "version_id": "ver_1",
            "node_count": 1,
            "nodes": [
                {
                    "node_id": "0000",
                    "parent_node_id": None,
                    "depth": 0,
                    "title": "Root",
                    "breadcrumb": "Manual Label / Root",
                    "page_start": 1,
                    "page_end": 3,
                    "route_summary": "Root summary",
                }
            ],
        }

        backend = _LegacyRoutingArtifactBackend(legacy_payload)
        with patch("app.services.storage_service._get_storage_backend", return_value=backend):
            payload = read_document_routing_index("minio://bucket/tenant/doc/version/routing_index.json")

        self.assertEqual(payload["schema_version"], ROUTING_ASSET_SCHEMA_VERSION)
        self.assertEqual(payload["routing_index_version"], ROUTING_ASSET_SCHEMA_VERSION)
        self.assertEqual(
            payload["readiness"],
            {
                "base_nodes": "ready",
                "route_docs": "deferred",
                "synthetic_queries": "deferred",
                "embeddings": "deferred",
            },
        )
        self.assertEqual(payload["node_count"], 1)
        self.assertEqual(payload["nodes"][0]["node_id"], "0000")
        self.assertIsNone(payload["nodes"][0]["contrastive_summary"])
        self.assertIsNone(payload["nodes"][0]["aliases_json"])
        self.assertIsNone(payload["nodes"][0]["keywords_json"])
        self.assertIsNone(payload["nodes"][0]["manual_profile_text"])

    def test_document_version_readiness_tracks_routing_lifecycle_only(self):
        version = DocumentVersion(
            id="ver_1",
            document_id="doc_1",
            version_no=1,
            storage_path="/tmp/source.pdf",
            file_hash="hash_1",
            parse_status="index_ready",
            routing_index_status="index_ready",
            routing_index_path="/tmp/routing_index.json",
            routing_index_version="v1",
        )

        self.assertEqual(version.routing_asset_schema_version, ROUTING_ASSET_SCHEMA_VERSION)
        self.assertTrue(version.routing_asset_is_ready)
        self.assertEqual(
            version.routing_asset_readiness,
            {
                "base_nodes": "ready",
                "route_docs": "deferred",
                "synthetic_queries": "deferred",
                "embeddings": "deferred",
            },
        )

        failed_version = DocumentVersion(
            id="ver_2",
            document_id="doc_1",
            version_no=2,
            storage_path="/tmp/source.pdf",
            file_hash="hash_2",
            parse_status="index_ready",
            routing_index_status="failed",
            routing_index_path=None,
            routing_index_version="v1",
        )

        self.assertFalse(failed_version.routing_asset_is_ready)
        self.assertEqual(failed_version.routing_asset_readiness["base_nodes"], "failed")
        self.assertEqual(failed_version.routing_asset_readiness["route_docs"], "deferred")


if __name__ == "__main__":
    unittest.main()
