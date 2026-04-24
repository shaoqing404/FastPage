import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("STORAGE_BACKEND", "local")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.core.db import Base
from app.models import Document, DocumentRoutingNode, DocumentVersion
from scripts.phase47 import routing_asset_maintenance as tool


HEAD_REVISION = "head-test"


def _engine_for_path(path: Path):
    return create_engine(f"sqlite:///{path}", future=True)


class TestRoutingAssetMaintenanceTool(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "routing-assets.db"
        self.engine = _engine_for_path(self.db_path)
        self.addCleanup(self.engine.dispose)
        self.database_url = f"sqlite:///{self.db_path}"

    def _create_current_schema(self, *, revision: str = HEAD_REVISION) -> None:
        Base.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES (:revision)"), {"revision": revision})

    def _insert_document_version(
        self,
        *,
        document_id: str,
        version_id: str,
        parse_status: str = "index_ready",
        parsed_structure_path: str | None = "/tmp/structure.json",
        routing_index_status: str = "uploaded",
        routing_index_path: str | None = None,
        node_summaries: list[str | None] | None = None,
    ) -> None:
        now = datetime.utcnow()
        with self.engine.begin() as conn:
            conn.execute(
                sa.insert(Document),
                {
                    "id": document_id,
                    "tenant_id": "tenant_1",
                    "workspace_id": "ws_1",
                    "owner_user_id": "user_1",
                    "display_name": f"Document {document_id}",
                    "source_filename": f"{document_id}.pdf",
                    "active_version_id": version_id,
                    "status": "index_ready",
                    "created_at": now,
                    "updated_at": now,
                },
            )
            conn.execute(
                sa.insert(DocumentVersion),
                {
                    "id": version_id,
                    "document_id": document_id,
                    "version_no": 1,
                    "storage_path": f"/tmp/{document_id}.pdf",
                    "file_hash": f"hash_{version_id}",
                    "parse_status": parse_status,
                    "parsed_structure_path": parsed_structure_path,
                    "parse_error": None,
                    "routing_index_status": routing_index_status,
                    "routing_index_path": routing_index_path,
                    "routing_index_error": None,
                    "routing_index_version": "v1",
                    "created_at": now,
                },
            )
            for index, summary in enumerate(node_summaries or []):
                conn.execute(
                    sa.insert(DocumentRoutingNode),
                    {
                        "id": f"rn_{version_id}_{index}",
                        "document_id": document_id,
                        "version_id": version_id,
                        "node_id": f"{index:04d}",
                        "parent_node_id": None,
                        "depth": 0,
                        "title": f"Node {index}",
                        "breadcrumb": f"Document {document_id} / Node {index}",
                        "page_start": 1,
                        "page_end": 1,
                        "route_summary": summary,
                        "contrastive_summary": None,
                        "aliases_json": None,
                        "keywords_json": None,
                        "manual_profile_text": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                )

    def test_scan_dry_run_reports_missing_failed_and_low_summary_versions(self):
        self._create_current_schema()
        self._insert_document_version(
            document_id="doc_ready",
            version_id="ver_ready",
            routing_index_status="index_ready",
            routing_index_path="/tmp/ready-routing.json",
            node_summaries=["Ready summary"],
        )
        self._insert_document_version(document_id="doc_missing", version_id="ver_missing")
        self._insert_document_version(
            document_id="doc_failed",
            version_id="ver_failed",
            routing_index_status="failed",
        )
        self._insert_document_version(
            document_id="doc_low",
            version_id="ver_low",
            routing_index_status="index_ready",
            routing_index_path="/tmp/low-routing.json",
            node_summaries=["Covered summary", None],
        )

        with patch.object(tool, "_migration_head", return_value=HEAD_REVISION):
            report = tool.build_scan_report(
                self.engine,
                summary_threshold=1.0,
                sample_limit=10,
                database_url=self.database_url,
            )

        self.assertEqual(report["status"], "dry_run")
        self.assertTrue(report["execute_required_for_mutation"])
        self.assertEqual(report["quality_summary"]["eligible_versions"], 4)
        self.assertEqual(report["quality_summary"]["missing_count"], 1)
        self.assertEqual(report["quality_summary"]["failed_count"], 1)
        self.assertEqual(report["quality_summary"]["low_summary_coverage_count"], 1)
        self.assertEqual(report["sample_validation"]["node_count"], 3)
        self.assertAlmostEqual(report["sample_validation"]["summary_coverage_ratio"], 0.666667)
        self.assertAlmostEqual(report["sample_validation"]["missing_rate"], 0.25)
        self.assertAlmostEqual(report["sample_validation"]["failure_rate"], 0.25)
        self.assertEqual(
            {item["version_id"] for item in report["planned_mutations"]["document_versions"]},
            {"ver_missing", "ver_failed"},
        )
        self.assertEqual(report["sample_validation"]["samples"]["low_summary_coverage"][0]["version_id"], "ver_low")

    def test_backfill_execute_is_gated_and_execute_writes_only_when_explicit(self):
        self._create_current_schema()
        structure_path = Path(self.temp_dir.name) / "structure.json"
        structure_path.write_text(
            """
            {
              "doc_name": "source.pdf",
              "structure": [
                {
                  "node_id": "0000",
                  "title": "Root",
                  "start_index": 1,
                  "end_index": 2,
                  "summary": "Root summary"
                }
              ]
            }
            """,
            encoding="utf-8",
        )
        self._insert_document_version(
            document_id="doc_missing",
            version_id="ver_missing",
            parsed_structure_path=str(structure_path),
        )
        args = SimpleNamespace(
            database_url=self.database_url,
            summary_threshold=1.0,
            sample_limit=5,
            include_low_summary=False,
            max_versions=None,
            execute=False,
            rollback_manifest=str(Path(self.temp_dir.name) / "rollback.json"),
        )

        with (
            patch.object(tool, "_migration_head", return_value=HEAD_REVISION),
            patch.object(tool, "_write_routing_index", side_effect=AssertionError("write should be gated")) as writer,
        ):
            dry_run = tool.backfill_payload(args)

        self.assertEqual(dry_run["status"], "dry_run")
        writer.assert_not_called()
        with Session(self.engine) as db:
            version = db.get(DocumentVersion, "ver_missing")
            node_count = db.scalar(
                select(sa.func.count()).select_from(DocumentRoutingNode).where(
                    DocumentRoutingNode.version_id == "ver_missing"
                )
            )
        assert version is not None
        self.assertEqual(version.routing_index_status, "uploaded")
        self.assertEqual(node_count, 0)

        args.execute = True
        with (
            patch.object(tool, "_migration_head", return_value=HEAD_REVISION),
            patch.object(tool, "_write_routing_index", return_value="/tmp/routing_index.json") as writer,
        ):
            executed = tool.backfill_payload(args)

        self.assertEqual(executed["status"], "completed")
        writer.assert_called_once()
        self.assertTrue(Path(args.rollback_manifest).exists())
        with Session(self.engine) as db:
            version = db.get(DocumentVersion, "ver_missing")
            nodes = db.scalars(
                select(DocumentRoutingNode).where(DocumentRoutingNode.version_id == "ver_missing")
            ).all()
        assert version is not None
        self.assertEqual(version.routing_index_status, "index_ready")
        self.assertEqual(version.routing_index_path, "/tmp/routing_index.json")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].route_summary, "Root summary")

    def test_scan_blocks_missing_schema_without_throwing(self):
        with patch.object(tool, "_migration_head", return_value=HEAD_REVISION):
            report = tool.build_scan_report(self.engine, database_url=self.database_url)

        self.assertEqual(report["status"], "blocked")
        self.assertIn("documents", report["schema"]["missing_tables"])
        self.assertIn("document_versions", report["schema"]["missing_tables"])
        self.assertEqual(report["planned_mutations"]["document_versions"], [])
        self.assertIn("runtime_reset.py rebuild", report["schema"]["next_step"])

    def test_scan_blocks_unmigrated_schema_without_querying_assets(self):
        self._create_current_schema(revision="old-revision")
        self._insert_document_version(document_id="doc_1", version_id="ver_1")

        with patch.object(tool, "_migration_head", return_value=HEAD_REVISION):
            report = tool.build_scan_report(self.engine, database_url=self.database_url)

        self.assertEqual(report["status"], "blocked")
        self.assertIn("database_not_at_alembic_head", report["schema"]["reasons"])
        self.assertEqual(report["schema"]["current_revisions"], ["old-revision"])
        self.assertIsNone(report["quality_summary"])


if __name__ == "__main__":
    unittest.main()
