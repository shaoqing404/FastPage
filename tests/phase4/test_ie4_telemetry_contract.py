import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.core.db import Base
from app.core.principal import Principal
from app.models import Document, DocumentVersion, ParseJob, RunObservationEvent, Tenant, Workspace
from app.services import runtime_observation_service
from app.services.runtime_observation_service import (
    get_routing_asset_debug_snapshot,
    get_runtime_observation_snapshot,
    record_run_observation_event,
)
from app.services.telemetry_service import (
    TELEMETRY_SCHEMA_VERSION,
    embedding_provider_telemetry,
    routing_asset_build_telemetry,
    routing_asset_item,
    telemetry_payload,
)


def _principal() -> Principal:
    user = SimpleNamespace(id="user_1", tenant_id="tenant_1")
    return Principal(
        kind="session",
        tenant_id="tenant_1",
        workspace_id="ws_1",
        tenant_membership_role="admin",
        tenant_membership_status="active",
        workspace_membership_role="admin",
        workspace_membership_status="active",
        workspace_permissions={"can_view_runs": True},
        user=user,
    )


class TestIE4TelemetryContract(unittest.TestCase):
    def test_embedding_provider_telemetry_is_sanitized_and_records_fallback(self):
        telemetry = embedding_provider_telemetry(
            requested_mode="auto",
            embedding_config={
                "enabled": True,
                "resolved_mode": "system",
                "provider_source": "system",
                "provider_type": "openai_compatible",
                "model": "openai/text-embedding-3-large",
                "base_url": "https://example.com/v1",
                "api_key": "secret",
                "fallback_reason": "provider_embedding_unavailable",
            },
        )

        self.assertEqual(telemetry["requested_mode"], "auto")
        self.assertEqual(telemetry["resolved_mode"], "system")
        self.assertEqual(telemetry["fallback_reason"], "provider_embedding_unavailable")
        self.assertNotIn("api_key", telemetry)
        self.assertNotIn("base_url", telemetry)

    def test_routing_asset_build_telemetry_counts_coverage_missing_and_failure(self):
        items = [
            routing_asset_item(
                document_id="doc_ready",
                version_id="ver_ready",
                routing_index_status="index_ready",
                routing_index_path="/tmp/routing.json",
                routing_index_version="v1",
            ),
            routing_asset_item(
                document_id="doc_missing",
                version_id="ver_missing",
                routing_index_status="uploaded",
                routing_index_path=None,
                routing_index_version="v1",
            ),
            routing_asset_item(
                document_id="doc_failed",
                version_id="ver_failed",
                routing_index_status="failed",
                routing_index_path=None,
                routing_index_version="v1",
            ),
        ]

        telemetry = telemetry_payload(
            routing_asset_build=routing_asset_build_telemetry(
                items=items,
                mode="backfill",
                dry_run=True,
                backfill=True,
                attempted=False,
            )
        )

        coverage = telemetry["routing_asset_build"]["coverage"]
        self.assertEqual(telemetry["schema_version"], TELEMETRY_SCHEMA_VERSION)
        self.assertEqual(coverage["total_count"], 3)
        self.assertEqual(coverage["ready_count"], 1)
        self.assertEqual(coverage["missing_count"], 1)
        self.assertEqual(coverage["failed_count"], 1)
        self.assertAlmostEqual(coverage["coverage_rate"], 0.333333)
        self.assertAlmostEqual(coverage["missing_rate"], 0.333333)
        self.assertAlmostEqual(coverage["failure_rate"], 0.333333)

    def test_record_observation_falls_back_to_ephemeral_without_table(self):
        engine = create_engine("sqlite:///:memory:", future=True)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        self.addCleanup(engine.dispose)

        async def scenario():
            with (
                patch.object(runtime_observation_service, "SessionLocal", SessionLocal),
                patch.object(runtime_observation_service, "publish_runtime_observation", new=AsyncMock()),
                patch.object(runtime_observation_service, "publish_chat_event", new=AsyncMock()),
            ):
                first = await record_run_observation_event(
                    run_kind="parse_job",
                    run_id="job_ephemeral",
                    tenant_id="tenant_1",
                    workspace_id="ws_1",
                    event_type="step_started",
                    step="routing_asset_build",
                )
                second = await record_run_observation_event(
                    run_kind="parse_job",
                    run_id="job_ephemeral",
                    tenant_id="tenant_1",
                    workspace_id="ws_1",
                    event_type="step_completed",
                    step="routing_asset_build",
                )
            return first, second

        first, second = asyncio.run(scenario())

        self.assertEqual(first["sequence_no"], 1)
        self.assertEqual(second["sequence_no"], 2)
        self.assertEqual(first["run_kind"], "parse_job")

    def test_parse_job_snapshot_works_without_observation_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(f"sqlite:///{Path(temp_dir) / 'snapshot.db'}", future=True)
            self.addCleanup(engine.dispose)
            Base.metadata.create_all(engine)
            RunObservationEvent.__table__.drop(engine)
            SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

            with SessionLocal() as db:
                db.add(
                    DocumentVersion(
                        id="ver_1",
                        document_id="doc_1",
                        version_no=1,
                        storage_path="/tmp/source.pdf",
                        file_hash="hash_1",
                        parse_status="index_ready",
                        parsed_structure_path="/tmp/structure.json",
                        routing_index_status="index_ready",
                        routing_index_path="/tmp/routing.json",
                    )
                )
                db.add(
                    ParseJob(
                        id="job_1",
                        tenant_id="tenant_1",
                        workspace_id="ws_1",
                        document_id="doc_1",
                        version_id="ver_1",
                        model="test-model",
                        status="index_ready",
                        current_step="index_ready",
                        progress_percent=100,
                    )
                )
                db.commit()

                snapshot = get_runtime_observation_snapshot(
                    db,
                    _principal(),
                    run_kind="parse_job",
                    run_id="job_1",
                )

        telemetry = snapshot["execution_context"]["telemetry"]
        coverage = telemetry["routing_asset_build"]["coverage"]
        self.assertEqual(snapshot["run_kind"], "parse_job")
        self.assertEqual(snapshot["events"], [])
        self.assertEqual(coverage["total_count"], 1)
        self.assertEqual(coverage["ready_count"], 1)

    def test_debug_routing_asset_snapshot_is_read_only_dry_run_backfill_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(f"sqlite:///{Path(temp_dir) / 'debug.db'}", future=True)
            self.addCleanup(engine.dispose)
            Base.metadata.create_all(engine)
            SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

            with SessionLocal() as db:
                db.add(Tenant(id="tenant_1", name="Tenant"))
                db.add(
                    Workspace(
                        id="ws_1",
                        tenant_id="tenant_1",
                        name="Workspace",
                        slug="workspace",
                        is_default=False,
                    )
                )
                db.add(
                    Document(
                        id="doc_ready",
                        tenant_id="tenant_1",
                        workspace_id="ws_1",
                        owner_user_id="user_1",
                        display_name="Ready",
                        source_filename="ready.pdf",
                    )
                )
                db.add(
                    Document(
                        id="doc_failed",
                        tenant_id="tenant_1",
                        workspace_id="ws_1",
                        owner_user_id="user_1",
                        display_name="Failed",
                        source_filename="failed.pdf",
                    )
                )
                db.add_all(
                    [
                        DocumentVersion(
                            id="ver_ready",
                            document_id="doc_ready",
                            version_no=1,
                            storage_path="/tmp/ready.pdf",
                            file_hash="hash_ready",
                            parse_status="index_ready",
                            routing_index_status="index_ready",
                            routing_index_path="/tmp/ready-routing.json",
                        ),
                        DocumentVersion(
                            id="ver_failed",
                            document_id="doc_failed",
                            version_no=1,
                            storage_path="/tmp/failed.pdf",
                            file_hash="hash_failed",
                            parse_status="index_ready",
                            routing_index_status="failed",
                            routing_index_path=None,
                        ),
                    ]
                )
                db.commit()

                snapshot = get_routing_asset_debug_snapshot(
                    db,
                    _principal(),
                    backfill=True,
                    sample_limit=5,
                )

        routing_build = snapshot["routing_asset_build"]
        self.assertTrue(routing_build["mode"]["dry_run"])
        self.assertTrue(routing_build["mode"]["backfill"])
        self.assertEqual(routing_build["mode"]["requested_mode"], "backfill")
        self.assertEqual(routing_build["coverage"]["total_count"], 2)
        self.assertEqual(routing_build["coverage"]["ready_count"], 1)
        self.assertEqual(routing_build["coverage"]["failed_count"], 1)
        self.assertEqual(snapshot["samples"]["failed"][0]["version_id"], "ver_failed")


if __name__ == "__main__":
    unittest.main()
