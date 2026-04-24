import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["STORAGE_BACKEND"] = "local"
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.core.config import get_settings

# These tests exercise parse artifacts and must not inherit a Settings object
# cached by modules imported earlier in the same unittest process.
get_settings.cache_clear()

from app.core.db import Base
from app.models import Document, DocumentRoutingNode, DocumentVersion, ParseJob
from app.models.routing_asset_contract import ROUTING_ASSET_SCHEMA_VERSION
from app.services.pageindex_service import RoutingBuildOptions, build_routing_index_payload, parse_pdf_to_structure
from app.services import parse_service


class TestParseRoutingIndexPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.engine = create_engine(f"sqlite:///{Path(self.temp_dir.name) / 'parse_routing_index.db'}", future=True)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        self.parse_observation_patcher = patch.object(
            parse_service,
            "_record_parse_observation",
            new=AsyncMock(),
        )
        self.parse_observation_patcher.start()
        self.addCleanup(self.parse_observation_patcher.stop)

        self.pdf_path = Path(self.temp_dir.name) / "source.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.4\n% PageIndex test pdf\n")

        self.document_id = "doc_1"
        self.version_id = "ver_1"
        self.job_id = "job_1"

        with self.SessionLocal() as db:
            db.add(
                Document(
                    id=self.document_id,
                    tenant_id="tenant_1",
                    workspace_id="ws_1",
                    owner_user_id="user_1",
                    display_name="Manual Label",
                    source_filename="source.pdf",
                    status="uploaded",
                )
            )
            db.add(
                DocumentVersion(
                    id=self.version_id,
                    document_id=self.document_id,
                    version_no=1,
                    storage_path=str(self.pdf_path),
                    file_hash="hash_1",
                    parse_status="uploaded",
                )
            )
            db.add(
                ParseJob(
                    id=self.job_id,
                    tenant_id="tenant_1",
                    workspace_id="ws_1",
                    document_id=self.document_id,
                    version_id=self.version_id,
                    model="test-model",
                    status="uploaded",
                    current_step="uploaded",
                    progress_percent=0,
                )
            )
            db.commit()

    def _parsed_result(self) -> dict:
        return {
            "doc_name": "source.pdf",
            "structure": [
                {
                    "node_id": "0000",
                    "title": "Root",
                    "start_index": 1,
                    "end_index": 3,
                    "summary": "Root summary",
                    "nodes": [
                        {
                            "node_id": "0001",
                            "title": "Child",
                            "start_index": 2,
                            "end_index": 3,
                            "summary": "Child summary",
                        }
                    ],
                }
            ],
        }

    def _updated_parsed_result(self) -> dict:
        return {
            "doc_name": "source.pdf",
            "structure": [
                {
                    "node_id": "0000",
                    "title": "Root",
                    "start_index": 1,
                    "end_index": 2,
                    "summary": "Updated root summary",
                }
            ],
        }

    def _mixed_summary_result(self) -> dict:
        return {
            "doc_name": "source.pdf",
            "structure": [
                {
                    "node_id": "0000",
                    "title": "Root",
                    "start_index": 1,
                    "end_index": 3,
                    "summary": "Root summary",
                    "nodes": [
                        {
                            "node_id": "0001",
                            "title": "Missing Summary",
                            "start_index": 2,
                            "end_index": 2,
                        },
                        {
                            "node_id": "0002",
                            "title": "Blank Summary",
                            "start_index": 3,
                            "end_index": 3,
                            "summary": "   ",
                        },
                    ],
                }
            ],
        }

    @patch("app.services.pageindex_service.page_index_main", return_value={"structure": []})
    @patch("app.services.pageindex_service.ConfigLoader")
    def test_parse_pdf_to_structure_does_not_force_node_summary_off(self, mock_config_loader, mock_page_index_main):
        mock_config_loader.return_value.load.return_value = SimpleNamespace()

        parse_pdf_to_structure("/tmp/source.pdf", "test-model")

        config = mock_config_loader.return_value.load.call_args.args[0]
        self.assertNotIn("if_add_node_summary", config)
        self.assertEqual(config["if_add_node_id"], "yes")
        mock_page_index_main.assert_called_once()

    def test_build_routing_index_payload_defaults_hooks_disabled(self):
        payload = build_routing_index_payload(
            self._parsed_result()["structure"],
            document_label="Manual Label",
            document_id=self.document_id,
            version_id=self.version_id,
            source_doc_name="source.pdf",
        )

        metadata = payload["build_metadata"]
        self.assertEqual(metadata["summary_coverage"]["total_nodes"], 2)
        self.assertEqual(metadata["summary_coverage"]["summary_count"], 2)
        self.assertEqual(metadata["summary_coverage"]["missing_summary_count"], 0)
        self.assertEqual(metadata["summary_coverage"]["coverage_state"], "complete")
        self.assertEqual(metadata["hook_results"]["route_docs"]["status"], "disabled")
        self.assertEqual(metadata["hook_results"]["synthetic_queries"]["status"], "disabled")
        self.assertEqual(metadata["hook_results"]["embeddings"]["status"], "disabled")
        self.assertEqual(metadata["execution_plan"]["async_backfill_steps"], [
            "route_doc_materialization",
            "synthetic_query_generation",
            "embedding_backfill",
        ])
        self.assertNotIn("route_docs", payload)
        self.assertEqual(
            payload["readiness"],
            {
                "base_nodes": "ready",
                "route_docs": "deferred",
                "synthetic_queries": "deferred",
                "embeddings": "deferred",
            },
        )

    def test_build_routing_index_payload_dry_run_hooks_do_not_materialize_assets(self):
        payload = build_routing_index_payload(
            self._parsed_result()["structure"],
            document_label="Manual Label",
            document_id=self.document_id,
            version_id=self.version_id,
            source_doc_name="source.pdf",
            build_options=RoutingBuildOptions(
                route_docs_mode="dry_run",
                synthetic_queries_mode="dry_run",
                embeddings_mode="dry_run",
            ),
        )

        hook_results = payload["build_metadata"]["hook_results"]
        self.assertEqual(hook_results["route_docs"]["status"], "dry_run")
        self.assertEqual(hook_results["route_docs"]["candidate_count"], 2)
        self.assertIn("Manual Label / Root", hook_results["route_docs"]["sample_route_doc"]["text"])
        self.assertEqual(hook_results["synthetic_queries"]["status"], "dry_run")
        self.assertEqual(hook_results["synthetic_queries"]["eligible_node_count"], 2)
        self.assertEqual(hook_results["embeddings"]["status"], "dry_run")
        self.assertEqual(hook_results["embeddings"]["eligible_node_count"], 2)
        self.assertNotIn("route_docs", payload)
        self.assertEqual(payload["readiness"]["route_docs"], "deferred")
        self.assertEqual(payload["readiness"]["synthetic_queries"], "deferred")
        self.assertEqual(payload["readiness"]["embeddings"], "deferred")

    def test_build_routing_index_payload_accepts_legacy_build_mode_aliases(self):
        payload = build_routing_index_payload(
            self._parsed_result()["structure"],
            document_label="Manual Label",
            document_id=self.document_id,
            version_id=self.version_id,
            source_doc_name="source.pdf",
            build_options=RoutingBuildOptions(
                route_docs_mode="persist",
                synthetic_queries_mode="off",
                embeddings_mode="on",
            ),
        )

        hook_results = payload["build_metadata"]["hook_results"]
        self.assertEqual(hook_results["route_docs"]["mode"], "enabled")
        self.assertEqual(hook_results["route_docs"]["status"], "ready")
        self.assertEqual(hook_results["synthetic_queries"]["mode"], "disabled")
        self.assertEqual(hook_results["embeddings"]["mode"], "enabled")
        self.assertEqual(hook_results["embeddings"]["status"], "pending_backfill")
        self.assertEqual(payload["readiness"]["route_docs"], "ready")
        self.assertEqual(payload["readiness"]["synthetic_queries"], "deferred")
        self.assertEqual(payload["readiness"]["embeddings"], "pending")
        self.assertEqual(len(payload["route_docs"]), 2)

    def test_run_parse_job_persists_routing_index_and_rows(self):
        with (
            patch.object(parse_service, "SessionLocal", self.SessionLocal),
            patch.object(parse_service, "parse_pdf_to_structure_async", return_value=self._parsed_result()),
            patch.object(parse_service, "write_document_structure", return_value="/tmp/structure.json") as mock_structure,
            patch.object(parse_service, "write_document_routing_index", return_value="/tmp/routing_index.json") as mock_routing,
        ):
            asyncio.run(parse_service.run_parse_job(self.job_id))

        with self.SessionLocal() as db:
            version = db.get(DocumentVersion, self.version_id)
            document = db.get(Document, self.document_id)
            job = db.get(ParseJob, self.job_id)
            routing_nodes = db.scalars(
                select(DocumentRoutingNode)
                .where(DocumentRoutingNode.version_id == self.version_id)
                .order_by(DocumentRoutingNode.depth, DocumentRoutingNode.node_id)
            ).all()

        self.assertIsNotNone(version)
        self.assertIsNotNone(document)
        self.assertIsNotNone(job)
        assert version is not None
        assert document is not None
        assert job is not None

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
        self.assertEqual(version.parse_status, "index_ready")
        self.assertEqual(version.routing_index_status, "index_ready")
        self.assertEqual(version.parsed_structure_path, "/tmp/structure.json")
        self.assertEqual(version.routing_index_path, "/tmp/routing_index.json")
        self.assertIsNone(version.routing_index_error)
        self.assertEqual(document.status, "index_ready")
        self.assertEqual(document.active_version_id, self.version_id)
        self.assertEqual(job.status, "index_ready")
        self.assertEqual(job.current_step, "index_ready")
        self.assertEqual(job.progress_percent, 100)
        self.assertIsNone(job.error_message)
        self.assertEqual(len(routing_nodes), 2)
        self.assertEqual(routing_nodes[0].node_id, "0000")
        self.assertEqual(routing_nodes[0].breadcrumb, "Manual Label / Root")
        self.assertEqual(routing_nodes[0].route_summary, "Root summary")
        self.assertEqual(routing_nodes[1].parent_node_id, "0000")
        self.assertEqual(routing_nodes[1].breadcrumb, "Manual Label / Root / Child")
        self.assertEqual(routing_nodes[1].route_summary, "Child summary")

        routing_payload = mock_routing.call_args.kwargs["data"]
        self.assertEqual(routing_payload["schema_version"], ROUTING_ASSET_SCHEMA_VERSION)
        self.assertEqual(routing_payload["routing_index_version"], ROUTING_ASSET_SCHEMA_VERSION)
        self.assertEqual(
            routing_payload["readiness"],
            {
                "base_nodes": "ready",
                "route_docs": "deferred",
                "synthetic_queries": "deferred",
                "embeddings": "deferred",
            },
        )
        self.assertEqual(routing_payload["document_label"], "Manual Label")
        self.assertEqual(routing_payload["source_doc_name"], "source.pdf")
        self.assertEqual(routing_payload["node_count"], 2)
        self.assertEqual(routing_payload["build_metadata"]["summary_coverage"]["coverage_state"], "complete")
        self.assertEqual(routing_payload["build_metadata"]["hook_results"]["route_docs"]["mode"], "disabled")
        self.assertEqual(
            routing_payload["build_metadata"]["execution_plan"]["sync_parse_job_steps"][-2:],
            ["write_routing_index", "replace_document_routing_node_rows"],
        )
        self.assertEqual(routing_payload["nodes"][0]["breadcrumb"], "Manual Label / Root")
        self.assertEqual(routing_payload["nodes"][1]["parent_node_id"], "0000")
        mock_structure.assert_called_once()
        mock_routing.assert_called_once()

    def test_run_parse_job_records_routing_index_failure_without_breaking_parse_status(self):
        with (
            patch.object(parse_service, "SessionLocal", self.SessionLocal),
            patch.object(parse_service, "parse_pdf_to_structure_async", return_value=self._parsed_result()),
            patch.object(parse_service, "write_document_structure", return_value="/tmp/structure.json"),
            patch.object(
                parse_service,
                "write_document_routing_index",
                side_effect=RuntimeError("routing write failed"),
            ) as mock_routing,
        ):
            asyncio.run(parse_service.run_parse_job(self.job_id))

        with self.SessionLocal() as db:
            version = db.get(DocumentVersion, self.version_id)
            document = db.get(Document, self.document_id)
            job = db.get(ParseJob, self.job_id)
            routing_node_count = db.scalar(
                select(func.count()).select_from(DocumentRoutingNode).where(
                    DocumentRoutingNode.version_id == self.version_id
                )
            )

        self.assertIsNotNone(version)
        self.assertIsNotNone(document)
        self.assertIsNotNone(job)
        assert version is not None
        assert document is not None
        assert job is not None

        self.assertEqual(version.routing_asset_schema_version, ROUTING_ASSET_SCHEMA_VERSION)
        self.assertFalse(version.routing_asset_is_ready)
        self.assertEqual(
            version.routing_asset_readiness,
            {
                "base_nodes": "failed",
                "route_docs": "deferred",
                "synthetic_queries": "deferred",
                "embeddings": "deferred",
            },
        )
        self.assertEqual(version.parse_status, "index_ready")
        self.assertEqual(version.routing_index_status, "failed")
        self.assertIsNone(version.routing_index_path)
        self.assertIn("RuntimeError", version.routing_index_error or "")
        self.assertIn("routing write failed", version.routing_index_error or "")
        self.assertEqual(document.status, "index_ready")
        self.assertEqual(job.status, "index_ready")
        self.assertEqual(job.current_step, "index_ready")
        self.assertEqual(job.progress_percent, 100)
        self.assertIsNone(job.error_message)
        self.assertEqual(routing_node_count, 0)
        mock_routing.assert_called_once()

    def test_run_parse_job_records_mixed_summary_coverage_asset_metadata(self):
        with (
            patch.object(parse_service, "SessionLocal", self.SessionLocal),
            patch.object(parse_service, "parse_pdf_to_structure_async", return_value=self._mixed_summary_result()),
            patch.object(parse_service, "write_document_structure", return_value="/tmp/structure.json"),
            patch.object(parse_service, "write_document_routing_index", return_value="/tmp/routing_index.json") as mock_routing,
        ):
            asyncio.run(parse_service.run_parse_job(self.job_id))

        with self.SessionLocal() as db:
            version = db.get(DocumentVersion, self.version_id)
            routing_nodes = db.scalars(
                select(DocumentRoutingNode)
                .where(DocumentRoutingNode.version_id == self.version_id)
                .order_by(DocumentRoutingNode.depth, DocumentRoutingNode.node_id)
            ).all()

        self.assertIsNotNone(version)
        assert version is not None

        self.assertEqual(version.parse_status, "index_ready")
        self.assertEqual(version.routing_index_status, "index_ready")
        self.assertEqual(len(routing_nodes), 3)
        self.assertEqual(routing_nodes[0].route_summary, "Root summary")
        self.assertIsNone(routing_nodes[1].route_summary)
        self.assertIsNone(routing_nodes[2].route_summary)

        routing_payload = mock_routing.call_args.kwargs["data"]
        coverage = routing_payload["build_metadata"]["summary_coverage"]
        self.assertEqual(coverage["total_nodes"], 3)
        self.assertEqual(coverage["summary_count"], 1)
        self.assertEqual(coverage["missing_summary_count"], 2)
        self.assertEqual(coverage["coverage_ratio"], 0.3333)
        self.assertEqual(coverage["coverage_state"], "partial")
        self.assertEqual(coverage["missing_summary_node_ids"], ["0001", "0002"])

    def test_run_parse_job_dry_run_hooks_write_metadata_without_assets(self):
        dry_run_settings = SimpleNamespace(
            routing_route_docs_build_mode="dry_run",
            routing_synthetic_queries_build_mode="dry_run",
            routing_embeddings_build_mode="dry_run",
        )
        with (
            patch.object(parse_service, "SessionLocal", self.SessionLocal),
            patch.object(parse_service, "settings", dry_run_settings),
            patch.object(parse_service, "parse_pdf_to_structure_async", return_value=self._parsed_result()),
            patch.object(parse_service, "write_document_structure", return_value="/tmp/structure.json"),
            patch.object(parse_service, "write_document_routing_index", return_value="/tmp/routing_index.json") as mock_routing,
        ):
            asyncio.run(parse_service.run_parse_job(self.job_id))

        with self.SessionLocal() as db:
            version = db.get(DocumentVersion, self.version_id)

        self.assertIsNotNone(version)
        assert version is not None
        self.assertEqual(version.parse_status, "index_ready")
        self.assertEqual(version.routing_index_status, "index_ready")

        routing_payload = mock_routing.call_args.kwargs["data"]
        hook_results = routing_payload["build_metadata"]["hook_results"]
        self.assertEqual(hook_results["route_docs"]["status"], "dry_run")
        self.assertEqual(hook_results["route_docs"]["candidate_count"], 2)
        self.assertEqual(hook_results["synthetic_queries"]["status"], "dry_run")
        self.assertEqual(hook_results["embeddings"]["status"], "dry_run")
        self.assertNotIn("route_docs", routing_payload)
        self.assertEqual(routing_payload["readiness"]["route_docs"], "deferred")
        self.assertEqual(routing_payload["readiness"]["synthetic_queries"], "deferred")
        self.assertEqual(routing_payload["readiness"]["embeddings"], "deferred")

    def test_run_parse_job_replaces_existing_routing_rows_for_same_version(self):
        second_job_id = "job_2"
        with self.SessionLocal() as db:
            db.add(
                ParseJob(
                    id=second_job_id,
                    tenant_id="tenant_1",
                    workspace_id="ws_1",
                    document_id=self.document_id,
                    version_id=self.version_id,
                    model="test-model",
                    status="uploaded",
                    current_step="uploaded",
                    progress_percent=0,
                )
            )
            db.commit()

        with (
            patch.object(parse_service, "SessionLocal", self.SessionLocal),
            patch.object(
                parse_service,
                "parse_pdf_to_structure_async",
                side_effect=[self._parsed_result(), self._updated_parsed_result()],
            ),
            patch.object(
                parse_service,
                "write_document_structure",
                side_effect=["/tmp/structure-v1.json", "/tmp/structure-v2.json"],
            ),
            patch.object(
                parse_service,
                "write_document_routing_index",
                side_effect=["/tmp/routing-v1.json", "/tmp/routing-v2.json"],
            ) as mock_routing,
        ):
            asyncio.run(parse_service.run_parse_job(self.job_id))
            asyncio.run(parse_service.run_parse_job(second_job_id))

        with self.SessionLocal() as db:
            version = db.get(DocumentVersion, self.version_id)
            first_job = db.get(ParseJob, self.job_id)
            second_job = db.get(ParseJob, second_job_id)
            routing_nodes = db.scalars(
                select(DocumentRoutingNode)
                .where(DocumentRoutingNode.version_id == self.version_id)
                .order_by(DocumentRoutingNode.depth, DocumentRoutingNode.node_id)
            ).all()

        self.assertIsNotNone(version)
        self.assertIsNotNone(first_job)
        self.assertIsNotNone(second_job)
        assert version is not None
        assert first_job is not None
        assert second_job is not None

        self.assertEqual(version.routing_asset_schema_version, ROUTING_ASSET_SCHEMA_VERSION)
        self.assertTrue(version.routing_asset_is_ready)
        self.assertEqual(version.parse_status, "index_ready")
        self.assertEqual(version.routing_index_status, "index_ready")
        self.assertEqual(version.parsed_structure_path, "/tmp/structure-v2.json")
        self.assertEqual(version.routing_index_path, "/tmp/routing-v2.json")
        self.assertIsNone(version.routing_index_error)
        self.assertEqual(first_job.status, "index_ready")
        self.assertEqual(second_job.status, "index_ready")
        self.assertEqual(len(routing_nodes), 1)
        self.assertEqual(routing_nodes[0].node_id, "0000")
        self.assertEqual(routing_nodes[0].route_summary, "Updated root summary")
        self.assertEqual(routing_nodes[0].breadcrumb, "Manual Label / Root")

        second_payload = mock_routing.call_args_list[1].kwargs["data"]
        self.assertEqual(second_payload["node_count"], 1)
        self.assertEqual(second_payload["build_metadata"]["summary_coverage"]["coverage_state"], "complete")
        self.assertEqual(second_payload["build_metadata"]["summary_coverage"]["missing_summary_count"], 0)


if __name__ == "__main__":
    unittest.main()
