import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

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

get_settings.cache_clear()

from scripts.phase47 import node_shadow_eval
from scripts.phase47 import real_manual_shadow_eval


class TestNodeShadowEval(unittest.TestCase):
    def _input_payload(self) -> dict:
        manual_ref = {
            "manual_key": "doc_1:ver_1",
            "document_id": "doc_1",
            "version_id": "ver_1",
            "document_label": "Alpha Manual",
            "version_label": "v1",
            "display_name": "Alpha Manual",
            "source_filename": "alpha.pdf",
            "storage_path": "/tmp/alpha.pdf",
            "parsed_structure_path": None,
            "routing_index_status": "uploaded",
            "routing_index_path": None,
            "routing_index_version": "v1",
        }
        node = {
            "manual_key": "doc_1:ver_1",
            "document_id": "doc_1",
            "version_id": "ver_1",
            "document_label": "Alpha Manual",
            "version_label": "v1",
            "source_filename": "alpha.pdf",
            "node_id": "n1",
            "node_key": "doc_1:ver_1:n1",
            "title": "Airport Approach",
            "breadcrumb": "Alpha Manual / Airport Approach",
            "page_start": 1,
            "page_end": 2,
            "page_span": 2,
            "depth": 1,
            "route_summary": "Airport approach guidance",
            "corpus_source": "document_routing_nodes",
            "inventory_source": "document_routing_nodes",
            "original_index": 0,
        }
        return {
            "question": "airport approach",
            "top_k": 1,
            "candidate_top_k": 1,
            "manual_gate_result": {"applied_manuals": [manual_ref]},
            "node_corpora": [
                {
                    "manual_key": "doc_1:ver_1",
                    "manual": manual_ref,
                    "corpus_source": "document_routing_nodes",
                    "nodes": [node],
                    "node_count": 1,
                    "fallback_reason": None,
                    "warning": None,
                }
            ],
            "outline_diagnostics": {
                "manuals": [
                    {
                        "document_id": "doc_1",
                        "version_id": "ver_1",
                        "selected_node_ids": ["n1"],
                    }
                ]
            },
            "final_citations": [{"document_id": "doc_1", "version_id": "ver_1", "node_id": "n1"}],
            "retrieve_candidates_latency_ms": 12,
        }

    def test_main_writes_json_report_from_input_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.json"
            output_path = Path(temp_dir) / "report.json"
            input_path.write_text(json.dumps(self._input_payload()), encoding="utf-8")

            node_shadow_eval.main([
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--format",
                "json",
            ])

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "node_shadow_eval_report_v1")
        self.assertEqual(payload["summary"]["run_count"], 1)
        self.assertIn("node_topk_overlap_with_outline", payload["summary"]["metrics"])
        self.assertEqual(payload["samples"][0]["shortlist"][0]["node_id"], "n1")
        self.assertEqual(
            payload["samples"][0]["metrics"]["node_topk_recall_of_final_citation_nodes"]["value"],
            1.0,
        )

    def test_main_accepts_artifact_exact_dense_source_for_legacy_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.json"
            output_path = Path(temp_dir) / "report.json"
            input_path.write_text(json.dumps(self._input_payload()), encoding="utf-8")

            node_shadow_eval.main([
                "--input",
                str(input_path),
                "--dense-source",
                "artifact-exact",
                "--embedding-mode",
                "system",
                "--output",
                str(output_path),
                "--format",
                "json",
            ])

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["query"]["dense_source"], "artifact-exact")
        self.assertEqual(payload["samples"][0]["dense"]["requested_dense_source"], "artifact_exact_scan")
        self.assertEqual(payload["samples"][0]["dense"]["dense_source"], "artifact_exact_scan")
        if not payload["samples"][0]["dense"]["enabled"]:
            self.assertIn("embedding_unavailable", payload["samples"][0]["dense"]["fallback_reason"])

    def test_markdown_report_includes_required_metric_names(self):
        payload = {
            "generated_at": "2026-04-24T00:00:00+00:00",
            "runtime": {
                "database_mode": "sqlite",
                "database_url": "sqlite:///:memory:",
                "system_embedding_enabled": False,
                "routing_embeddings_build_mode": "disabled",
            },
            "summary": {
                "run_count": 1,
                "metrics": {
                    "node_topk_overlap_with_outline": {"avg_value": 1.0},
                    "node_topk_recall_of_final_citation_nodes": {"avg_value": 1.0},
                    "hybrid_vs_lexical_gain": {"avg_value": None},
                    "latency_delta": {"node_shadow_latency_ms_avg": 0.0},
                    "zero_hit_rate": {"avg_value": 0.0},
                    "fallback_needed_rate": {"avg_value": 0.0, "by_source": {}},
                },
                "corpus_source_counts": {"document_routing_nodes": 1},
                "dense_fallback_counts": {"embedding_mode_disabled": 1},
            },
        }

        markdown = node_shadow_eval._markdown_report(payload)

        self.assertIn("node_topk_overlap_with_outline", markdown)
        self.assertIn("node_topk_recall_of_final_citation_nodes", markdown)
        self.assertIn("fallback_needed_rate", markdown)

    def test_real_manual_cohort_resolves_leaf_gold_from_title_and_pages(self):
        manual_ref = {
            "manual_key": "doc_1:ver_1",
            "document_id": "doc_1",
            "version_id": "ver_1",
            "document_label": "Manual",
            "version_label": "v1",
            "display_name": "Manual",
            "source_filename": "manual.pdf",
            "routing_index_status": "uploaded",
            "routing_index_path": None,
            "routing_index_version": "v1",
        }
        structure = {
            "doc_name": "Manual",
            "structure": [
                {
                    "title": "6.0 Ops",
                    "node_id": "0079",
                    "start_index": 350,
                    "end_index": 360,
                    "summary": "chapter",
                    "nodes": [
                        {
                            "title": "6.9 Special Airports",
                            "node_id": "0080",
                            "start_index": 353,
                            "end_index": 360,
                            "summary": "special airport list",
                        }
                    ],
                }
            ],
        }
        corpus, _summary = real_manual_shadow_eval.build_node_corpus_from_structure(structure, manual_ref)
        index = real_manual_shadow_eval._node_index(corpus["nodes"])

        samples, summary = real_manual_shadow_eval.build_real_manual_cohort(
            [
                {
                    "id": 1,
                    "question": "Where are special airports?",
                    "reference_answer": "answer",
                    "leaf_title": "6.9 Special Airports",
                    "leaf_path": "6.0 Ops 6.9 Special Airports",
                    "page_start": 353,
                    "page_end": 360,
                    "kind": "fact",
                }
            ],
            nodes=corpus["nodes"],
            node_index=index,
            document_id="doc_1",
            version_id="ver_1",
        )

        self.assertEqual(samples[0]["gold"]["exact_node_ids"], ["0080"])
        self.assertEqual(samples[0]["gold"]["gold_source"], "leaf_title_page_exact")
        self.assertEqual(summary["questions_json_count"], 1)
        self.assertEqual(summary["p0_count"], 3)

    def test_real_manual_relaxed_recall_counts_ancestor_match_per_gold_node(self):
        node_index = {
            "relaxed_by_node_id": {
                "0080": {"0079", "0080", "0080a"},
            }
        }

        self.assertEqual(
            real_manual_shadow_eval._relaxed_recall({"0079"}, ["0080"], node_index["relaxed_by_node_id"]),
            1.0,
        )
        self.assertEqual(
            real_manual_shadow_eval._exact_recall({"0079"}, ["0080"]),
            0.0,
        )

    def test_es_shadow_dense_source_falls_back_without_es_runtime(self):
        """--dense-source es-shadow with ROUTING_NODE_ES_ENABLED=false must safely fall back.

        B4.2 runtime does not fall back to artifact exact scan. The report must
        still be valid JSON and contain the expected dense.fallback_reason key.

        This test verifies the Conditional-GO gate condition:
        code and mock tests pass even without a real ES runtime.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.json"
            output_path = Path(temp_dir) / "report.json"
            input_path.write_text(json.dumps(self._input_payload()), encoding="utf-8")

            # es-shadow is requested but ES is disabled (default config)
            node_shadow_eval.main([
                "--input",
                str(input_path),
                "--dense-source",
                "es-shadow",
                "--embedding-mode",
                "off",
                "--output",
                str(output_path),
                "--format",
                "json",
            ])

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "node_shadow_eval_report_v1")
        self.assertEqual(payload["query"]["dense_source"], "es-shadow")
        # ES is disabled by default → dense must not be enabled
        sample_dense = payload["samples"][0]["dense"]
        self.assertFalse(sample_dense["enabled"])
        # Fallback reason must be present
        self.assertIsNotNone(sample_dense.get("fallback_reason"))
        # Runtime must report ES disabled
        self.assertFalse(payload["runtime"]["routing_node_es_enabled"])

    def test_es_check_flag_adds_es_check_to_runtime_snapshot(self):
        """--es-check flag must add an es_check dict to the runtime snapshot.

        Without a real ES, es_check.es_available should be False and
        unavailable_reason should explain why.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.json"
            output_path = Path(temp_dir) / "report.json"
            input_path.write_text(json.dumps(self._input_payload()), encoding="utf-8")

            node_shadow_eval.main([
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--format",
                "json",
                "--es-check",
            ])

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertIn("es_check", payload["runtime"])
        es_check = payload["runtime"]["es_check"]
        self.assertIn("es_available", es_check)
        self.assertIn("unavailable_reason", es_check)
        self.assertIn("real_es_verified", es_check)
        # In test env, ES is disabled by default
        self.assertFalse(es_check["es_available"])
        self.assertIsNotNone(es_check["unavailable_reason"])


if __name__ == "__main__":
    unittest.main()
