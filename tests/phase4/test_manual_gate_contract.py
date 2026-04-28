import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.services import chat_service, compliance_service, routing_consumer_service
from app.services.compliance_service import _normalize_retrieval_config
from app.services.routing_consumer_service import (
    apply_manual_gate_full_retry,
    build_manual_gate_ref,
    build_manual_inventory,
    finalize_manual_gate_shadow_eval,
    manual_gate_error_result,
    run_manual_gate,
    tokenize_routing_text,
)
from app.services.telemetry_service import manual_gate_telemetry


class TestManualGateContract(unittest.TestCase):
    def _manual_ref(self, document_id: str, version_id: str, label: str, *, source_filename: str | None = None) -> dict:
        return build_manual_gate_ref(
            document_id=document_id,
            version_id=version_id,
            document_label=label,
            version_label="v1",
            display_name=label,
            source_filename=source_filename or f"{label}.pdf",
            storage_path=f"/tmp/{document_id}.pdf",
            parsed_structure_path=f"/tmp/{document_id}.json",
            routing_index_status="uploaded",
            routing_index_path=None,
            routing_index_version="v1",
        )

    def _db_without_routing_rows(self) -> MagicMock:
        db = MagicMock()
        db.scalars.return_value.all.return_value = []
        return db

    def _db_with_routing_rows(self, *rows: SimpleNamespace) -> MagicMock:
        db = MagicMock()
        db.scalars.return_value.all.return_value = list(rows)
        return db

    def _routing_row(
        self,
        version_id: str,
        *,
        title: str = "Inventory",
        breadcrumb: str | None = None,
        depth: int = 1,
        page_start: int = 1,
        page_end: int = 2,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            version_id=version_id,
            node_id=f"{version_id}_node",
            title=title,
            breadcrumb=breadcrumb or title,
            depth=depth,
            page_start=page_start,
            page_end=page_end,
        )

    def test_tokenize_routing_text_keeps_ascii_and_cjk_tokens(self):
        tokens = tokenize_routing_text("B737-800 特殊机场 飞行程序 QRH.2026")

        self.assertIn("b737-800", tokens)
        self.assertIn("b737", tokens)
        self.assertIn("800", tokens)
        self.assertIn("特殊机场", tokens)
        self.assertIn("特殊", tokens)
        self.assertIn("机场", tokens)
        self.assertIn("qrh.2026", tokens)

    def test_build_manual_inventory_prefers_routing_rows(self):
        manual_ref = self._manual_ref("doc_1", "ver_1", "Alpha Manual")
        row = SimpleNamespace(
            node_id="n1",
            title="Special Airport",
            breadcrumb="Alpha Manual / Special Airport",
            depth=2,
            page_start=10,
            page_end=11,
        )

        inventory = build_manual_inventory(manual_ref, routing_rows=[row])

        self.assertEqual(inventory["inventory_source"], "document_routing_nodes")
        self.assertEqual(inventory["inventory_node_count"], 1)
        self.assertEqual(inventory["inventory_nodes"][0]["node_id"], "n1")

    @patch("app.services.routing_consumer_service.load_structure_file")
    @patch("app.services.routing_consumer_service.read_document_routing_index")
    def test_build_manual_inventory_uses_routing_index_before_structure(self, mock_read_index, mock_load_structure):
        manual_ref = self._manual_ref("doc_1", "ver_1", "Alpha Manual")
        manual_ref["routing_index_path"] = "minio://bucket/doc_1/routing_index.json"
        mock_read_index.return_value = {
            "nodes": [
                {
                    "node_id": "n-routing",
                    "title": "Airport Notes",
                    "breadcrumb": "Alpha Manual / Airport Notes",
                    "depth": 1,
                    "page_start": 1,
                    "page_end": 2,
                }
            ]
        }

        inventory = build_manual_inventory(manual_ref, routing_rows=[])

        self.assertEqual(inventory["inventory_source"], "routing_index_json")
        self.assertEqual(inventory["inventory_nodes"][0]["node_id"], "n-routing")
        mock_load_structure.assert_not_called()

    @patch("app.services.routing_consumer_service.load_structure_file")
    @patch("app.services.routing_consumer_service.read_document_routing_index", side_effect=RuntimeError("boom"))
    def test_build_manual_inventory_falls_back_to_structure_then_metadata(self, _mock_read_index, mock_load_structure):
        manual_ref = self._manual_ref("doc_1", "ver_1", "Alpha Manual")
        manual_ref["routing_index_path"] = "minio://bucket/doc_1/routing_index.json"
        mock_load_structure.return_value = [
            {
                "node_id": "n-structure",
                "title": "Special Procedures",
                "start_index": 3,
                "end_index": 5,
                "nodes": [],
            }
        ]

        inventory = build_manual_inventory(manual_ref, routing_rows=[])

        self.assertEqual(inventory["inventory_source"], "structure_json")
        self.assertEqual(inventory["inventory_nodes"][0]["node_id"], "n-structure")
        self.assertEqual(inventory["inventory_warning"], "routing_index_json_unavailable:RuntimeError")

        mock_load_structure.side_effect = RuntimeError("structure-boom")
        inventory = build_manual_inventory(manual_ref, routing_rows=[])
        self.assertEqual(inventory["inventory_source"], "metadata_only")
        self.assertEqual(inventory["inventory_node_count"], 0)
        self.assertEqual(inventory["inventory_warning"], "structure_json_unavailable:RuntimeError")

    def test_run_manual_gate_off_mode_preserves_full_manual_list(self):
        manual_refs = [
            self._manual_ref("doc_1", "ver_1", "Alpha Manual"),
            self._manual_ref("doc_2", "ver_2", "Bravo Airport Manual"),
        ]

        result = run_manual_gate(
            self._db_without_routing_rows(),
            question="bravo airport",
            manual_refs=manual_refs,
            requested_mode="off",
            default_mode="off",
            allow_live=False,
        )

        self.assertEqual(result["effective_mode"], "off")
        self.assertEqual(result["applied_manuals"], manual_refs)
        self.assertEqual(result["diagnostics"]["applied_selected_count"], len(manual_refs))

    def test_run_manual_gate_shadow_mode_preserves_full_manual_list(self):
        manual_refs = [
            self._manual_ref("doc_1", "ver_1", "Alpha Manual"),
            self._manual_ref("doc_2", "ver_2", "Bravo Airport Manual"),
        ]

        result = run_manual_gate(
            self._db_without_routing_rows(),
            question="bravo airport",
            manual_refs=manual_refs,
            requested_mode="shadow",
            default_mode="off",
            allow_live=False,
        )

        self.assertEqual(result["effective_mode"], "shadow")
        self.assertEqual(result["applied_manuals"], manual_refs)
        self.assertIn("manuals", result["diagnostics"])

    def test_run_manual_gate_live_is_deferred_without_allow_live(self):
        manual_refs = [
            self._manual_ref("doc_1", "ver_1", "Alpha Manual"),
            self._manual_ref("doc_2", "ver_2", "Bravo Airport Manual"),
        ]

        result = run_manual_gate(
            self._db_without_routing_rows(),
            question="bravo airport",
            manual_refs=manual_refs,
            requested_mode="live",
            default_mode="off",
            allow_live=False,
        )

        self.assertEqual(result["effective_mode"], "shadow")
        self.assertEqual(result["fallback_reason"], "live_deferred_until_a3")
        self.assertEqual(result["applied_manuals"], manual_refs)

    def test_chat_live_top1_prunes_to_selected_manual(self):
        manual_refs = [
            self._manual_ref("hydraulic_doc", "ver_hyd", "Hydraulic Pump Pressure Accumulator"),
            self._manual_ref("weather_doc", "ver_wx", "Weather Radar"),
            self._manual_ref("cabin_doc", "ver_cabin", "Cabin Service"),
        ]

        result = run_manual_gate(
            self._db_with_routing_rows(
                self._routing_row("ver_hyd", title="Hydraulic Pump Pressure Accumulator"),
                self._routing_row("ver_wx"),
                self._routing_row("ver_cabin"),
            ),
            question="hydraulic pump pressure accumulator",
            manual_refs=manual_refs,
            requested_mode="live",
            default_mode="off",
            allow_live=True,
        )

        self.assertEqual(result["effective_mode"], "live")
        self.assertEqual(result["decision"], "select_top1")
        self.assertEqual([manual["document_id"] for manual in result["applied_manuals"]], ["hydraulic_doc"])
        self.assertEqual(result["diagnostics"]["applied_selection"], "select_top1")

    def test_chat_live_top2_prunes_to_two_manuals(self):
        manual_refs = [
            self._manual_ref("bravo_approach_doc", "ver_ba", "Bravo Approach"),
            self._manual_ref("bravo_doc", "ver_b", "Bravo Manual"),
            self._manual_ref("zulu_doc", "ver_z", "Zulu Manual"),
        ]

        result = run_manual_gate(
            self._db_with_routing_rows(
                self._routing_row("ver_ba"),
                self._routing_row("ver_b"),
                self._routing_row("ver_z"),
            ),
            question="bravo approach",
            manual_refs=manual_refs,
            requested_mode="live",
            default_mode="off",
            allow_live=True,
        )

        self.assertEqual(result["effective_mode"], "live")
        self.assertEqual(result["decision"], "select_top2")
        self.assertEqual(
            [manual["document_id"] for manual in result["applied_manuals"]],
            ["bravo_approach_doc", "bravo_doc"],
        )
        self.assertEqual(result["diagnostics"]["applied_selection"], "select_top2")

    def test_chat_live_ambiguous_scores_fall_back_to_full_manuals(self):
        manual_refs = [
            self._manual_ref("bravo_approach_doc", "ver_ba", "Bravo Approach"),
            self._manual_ref("bravo_airport_doc", "ver_bp", "Bravo Airport"),
        ]

        result = run_manual_gate(
            self._db_with_routing_rows(
                self._routing_row("ver_ba"),
                self._routing_row("ver_bp"),
            ),
            question="bravo",
            manual_refs=manual_refs,
            requested_mode="live",
            default_mode="off",
            allow_live=True,
        )

        self.assertEqual(result["decision"], "fallback_full")
        self.assertEqual(result["fallback_reason"], "ambiguous_manual_scores")
        self.assertEqual(result["applied_manuals"], manual_refs)

    def test_chat_live_missing_inventory_falls_back_to_full_manuals(self):
        manual_refs = [
            self._manual_ref("hydraulic_doc", "ver_hyd", "Hydraulic Pump Pressure Accumulator"),
            self._manual_ref("weather_doc", "ver_wx", "Weather Radar"),
            self._manual_ref("cabin_doc", "ver_cabin", "Cabin Service"),
        ]

        result = run_manual_gate(
            self._db_without_routing_rows(),
            question="hydraulic pump pressure accumulator",
            manual_refs=manual_refs,
            requested_mode="live",
            default_mode="off",
            allow_live=True,
        )

        self.assertEqual(result["decision"], "fallback_full")
        self.assertEqual(result["fallback_reason"], "missing_inventory")
        self.assertEqual(result["applied_manuals"], manual_refs)

    def test_chat_live_zero_hit_full_retry_updates_diagnostics_and_telemetry(self):
        manual_refs = [
            self._manual_ref("hydraulic_doc", "ver_hyd", "Hydraulic Pump Pressure Accumulator"),
            self._manual_ref("weather_doc", "ver_wx", "Weather Radar"),
            self._manual_ref("cabin_doc", "ver_cabin", "Cabin Service"),
        ]
        result = run_manual_gate(
            self._db_with_routing_rows(
                self._routing_row("ver_hyd", title="Hydraulic Pump Pressure Accumulator"),
                self._routing_row("ver_wx"),
                self._routing_row("ver_cabin"),
            ),
            question="hydraulic pump pressure accumulator",
            manual_refs=manual_refs,
            requested_mode="live",
            default_mode="off",
            allow_live=True,
        )

        retry_reason, retry_trigger = chat_service._manual_gate_full_retry_reason(
            result,
            manual_refs,
            candidate_count=0,
            context_blocks=[],
        )
        apply_manual_gate_full_retry(
            result,
            manual_refs,
            fallback_reason=retry_reason,
            trigger=retry_trigger,
        )
        telemetry = manual_gate_telemetry(gate_result=result)

        self.assertEqual(retry_reason, "zero_hit_full_retry")
        self.assertEqual(result["fallback_reason"], "zero_hit_full_retry")
        self.assertEqual(result["applied_manuals"], manual_refs)
        self.assertTrue(result["diagnostics"]["zero_hit_retry"]["applied"])
        self.assertEqual(result["diagnostics"]["applied_selection"], "full_manuals_after_retry")
        self.assertTrue(telemetry["zero_hit_retry"]["applied"])
        self.assertEqual(len(telemetry["selected_manuals"]), 1)
        self.assertEqual(len(telemetry["applied_manuals"]), 3)

    def test_chat_live_empty_context_full_retry_reason(self):
        manual_refs = [
            self._manual_ref("hydraulic_doc", "ver_hyd", "Hydraulic Pump Pressure Accumulator"),
            self._manual_ref("weather_doc", "ver_wx", "Weather Radar"),
            self._manual_ref("cabin_doc", "ver_cabin", "Cabin Service"),
        ]
        result = run_manual_gate(
            self._db_with_routing_rows(
                self._routing_row("ver_hyd", title="Hydraulic Pump Pressure Accumulator"),
                self._routing_row("ver_wx"),
                self._routing_row("ver_cabin"),
            ),
            question="hydraulic pump pressure accumulator",
            manual_refs=manual_refs,
            requested_mode="live",
            default_mode="off",
            allow_live=True,
        )

        retry_reason, retry_trigger = chat_service._manual_gate_full_retry_reason(
            result,
            manual_refs,
            candidate_count=2,
            context_blocks=[""],
        )

        self.assertEqual(retry_reason, "empty_context_full_retry")
        self.assertEqual(retry_trigger, "empty_context")

    def test_chat_live_flag_rollback_returns_to_shadow_full_manuals(self):
        manual_refs = [
            self._manual_ref("hydraulic_doc", "ver_hyd", "Hydraulic Pump Pressure Accumulator"),
            self._manual_ref("weather_doc", "ver_wx", "Weather Radar"),
            self._manual_ref("cabin_doc", "ver_cabin", "Cabin Service"),
        ]
        original = getattr(chat_service.settings, "retrieval_manual_gate_chat_live_enabled", False)
        try:
            chat_service.settings.retrieval_manual_gate_chat_live_enabled = False
            result = run_manual_gate(
                self._db_with_routing_rows(
                    self._routing_row("ver_hyd", title="Hydraulic Pump Pressure Accumulator"),
                    self._routing_row("ver_wx"),
                    self._routing_row("ver_cabin"),
                ),
                question="hydraulic pump pressure accumulator",
                manual_refs=manual_refs,
                requested_mode="live",
                default_mode="off",
                allow_live=chat_service._chat_manual_gate_allow_live(),
                live_deferred_reason=chat_service.CHAT_MANUAL_GATE_LIVE_DEFERRED_REASON,
            )
        finally:
            chat_service.settings.retrieval_manual_gate_chat_live_enabled = original

        self.assertEqual(result["effective_mode"], "shadow")
        self.assertEqual(result["fallback_reason"], "chat_live_disabled")
        self.assertEqual(result["applied_manuals"], manual_refs)

    def test_compliance_requested_live_is_deferred_and_does_not_prune(self):
        manual_refs = [
            self._manual_ref("hydraulic_doc", "ver_hyd", "Hydraulic Pump Pressure Accumulator"),
            self._manual_ref("weather_doc", "ver_wx", "Weather Radar"),
            self._manual_ref("cabin_doc", "ver_cabin", "Cabin Service"),
        ]

        result = run_manual_gate(
            self._db_with_routing_rows(
                self._routing_row("ver_hyd", title="Hydraulic Pump Pressure Accumulator"),
                self._routing_row("ver_wx"),
                self._routing_row("ver_cabin"),
            ),
            question="hydraulic pump pressure accumulator",
            manual_refs=manual_refs,
            requested_mode="live",
            default_mode="off",
            allow_live=compliance_service._compliance_manual_gate_allow_live(),
            live_deferred_reason=compliance_service.COMPLIANCE_MANUAL_GATE_LIVE_DEFERRED_REASON,
        )

        self.assertEqual(result["effective_mode"], "shadow")
        self.assertEqual(result["fallback_reason"], "compliance_live_disabled")
        self.assertEqual(result["applied_manuals"], manual_refs)

    def test_manual_gate_shadow_eval_uses_ranked_manual_order(self):
        manual_refs = [
            self._manual_ref("a_doc", "ver_1", "Alpha Manual"),
            self._manual_ref("b_doc", "ver_2", "Bravo Airport Manual"),
        ]
        result = run_manual_gate(
            self._db_without_routing_rows(),
            question="bravo airport",
            manual_refs=manual_refs,
            requested_mode="shadow",
            default_mode="off",
            allow_live=False,
        )

        shadow_eval = finalize_manual_gate_shadow_eval(
            result,
            [
                {
                    "document_id": "b_doc",
                    "version_id": "ver_2",
                }
            ],
        )

        self.assertEqual(result["diagnostics"]["predicted_selected_manual_ids"][0], "b_doc:ver_2")
        self.assertTrue(shadow_eval["top1_hit_final_citation_manuals"])
        self.assertGreaterEqual(shadow_eval["citation_recall_at_top1"], 1.0)

    def test_manual_gate_telemetry_compacts_shadow_eval(self):
        manual_refs = [self._manual_ref("doc_1", "ver_1", "Bravo Airport Manual")]
        result = run_manual_gate(
            self._db_without_routing_rows(),
            question="bravo airport",
            manual_refs=manual_refs,
            requested_mode="shadow",
            default_mode="off",
            allow_live=False,
        )
        finalize_manual_gate_shadow_eval(
            result,
            [
                {
                    "document_id": "doc_1",
                    "version_id": "ver_1",
                }
            ],
        )

        payload = manual_gate_telemetry(gate_result=result)

        self.assertEqual(payload["effective_mode"], "shadow")
        self.assertIn("shadow_eval", payload)
        self.assertIn("manual_gate_latency_ms", payload["shadow_eval"])

    def test_manual_gate_error_result_falls_back_to_full_manuals(self):
        manual_refs = [
            self._manual_ref("doc_1", "ver_1", "Alpha Manual"),
            self._manual_ref("doc_2", "ver_2", "Bravo Manual"),
        ]

        result = manual_gate_error_result(
            manual_refs=manual_refs,
            requested_mode="shadow",
            default_mode="off",
            allow_live=False,
            error=RuntimeError("broken"),
        )

        self.assertEqual(result["effective_mode"], "off")
        self.assertEqual(result["decision"], "fallback_full")
        self.assertEqual(result["applied_manuals"], manual_refs)
        self.assertEqual(result["diagnostics"]["error"]["type"], "RuntimeError")

    def test_chat_and_compliance_use_same_shared_manual_gate_helpers(self):
        self.assertIs(chat_service.run_manual_gate, routing_consumer_service.run_manual_gate)
        self.assertIs(compliance_service.run_manual_gate, routing_consumer_service.run_manual_gate)
        self.assertIs(chat_service.build_manual_gate_ref, routing_consumer_service.build_manual_gate_ref)
        self.assertIs(compliance_service.build_manual_gate_ref, routing_consumer_service.build_manual_gate_ref)

    def test_compliance_retrieval_config_preserves_manual_gate_mode(self):
        normalized = _normalize_retrieval_config({"manual_gate_mode": "shadow"})

        self.assertEqual(normalized["manual_gate_mode"], "shadow")


if __name__ == "__main__":
    unittest.main()
