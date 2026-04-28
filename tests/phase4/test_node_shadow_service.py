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

from app.services.node_embedding_service import NodeDenseSearchResult
from app.services.node_shadow_service import (
    evaluate_node_shadow_metrics,
    load_node_corpus_for_manual,
    run_node_shadow_replay,
    score_node_corpora,
)


class TestNodeShadowService(unittest.TestCase):
    def _manual_ref(self) -> dict:
        return {
            "manual_key": "doc_1:ver_1",
            "document_id": "doc_1",
            "version_id": "ver_1",
            "document_label": "Alpha Manual",
            "version_label": "v1",
            "display_name": "Alpha Manual",
            "source_filename": "alpha.pdf",
            "storage_path": "/tmp/alpha.pdf",
            "parsed_structure_path": "/tmp/alpha-structure.json",
            "routing_index_status": "index_ready",
            "routing_index_path": "/tmp/alpha-routing.json",
            "routing_index_version": "v1",
        }

    def _row(self, node_id: str = "n1", title: str = "Airport Approach") -> SimpleNamespace:
        return SimpleNamespace(
            node_id=node_id,
            parent_node_id=None,
            title=title,
            breadcrumb=f"Alpha Manual / {title}",
            depth=1,
            page_start=10,
            page_end=12,
            route_summary="Landing and airport approach guidance",
            contrastive_summary=None,
            aliases_json='["approach"]',
            keywords_json='["airport"]',
            manual_profile_text="flight operations",
        )

    def test_load_node_corpus_prefers_routing_rows_and_preserves_optional_fields(self):
        with (
            patch("app.services.node_shadow_service.read_document_routing_index") as mock_read_index,
            patch("app.services.node_shadow_service.load_structure_file") as mock_load_structure,
        ):
            corpus = load_node_corpus_for_manual(self._manual_ref(), routing_rows=[self._row()])

        self.assertEqual(corpus["corpus_source"], "document_routing_nodes")
        self.assertEqual(corpus["node_count"], 1)
        self.assertEqual(corpus["nodes"][0]["route_summary"], "Landing and airport approach guidance")
        self.assertEqual(corpus["nodes"][0]["keywords"], ["airport"])
        mock_read_index.assert_not_called()
        mock_load_structure.assert_not_called()

    @patch("app.services.node_shadow_service.load_structure_file")
    @patch("app.services.node_shadow_service.read_document_routing_index")
    def test_load_node_corpus_fallback_chain_uses_index_then_structure_then_metadata(self, mock_read_index, mock_load_structure):
        mock_read_index.return_value = {
            "nodes": [
                {
                    "node_id": "idx_1",
                    "title": "Routing Index Node",
                    "breadcrumb": "Alpha / Routing Index Node",
                    "depth": 2,
                    "page_start": 1,
                    "page_end": 2,
                    "route_summary": "index summary",
                }
            ]
        }

        corpus = load_node_corpus_for_manual(self._manual_ref(), routing_rows=[])

        self.assertEqual(corpus["corpus_source"], "routing_index_json")
        self.assertEqual(corpus["nodes"][0]["node_id"], "idx_1")
        mock_load_structure.assert_not_called()

        mock_read_index.side_effect = RuntimeError("missing")
        mock_load_structure.return_value = [
            {
                "node_id": "struct_1",
                "title": "Structure Node",
                "start_index": 3,
                "end_index": 4,
                "summary": "structure summary",
            }
        ]

        corpus = load_node_corpus_for_manual(self._manual_ref(), routing_rows=[])

        self.assertEqual(corpus["corpus_source"], "structure_json")
        self.assertEqual(corpus["nodes"][0]["route_summary"], "structure summary")
        self.assertEqual(corpus["warning"], "routing_index_json_unavailable:RuntimeError")

        manual_ref = self._manual_ref()
        manual_ref["routing_index_path"] = None
        manual_ref["parsed_structure_path"] = None
        corpus = load_node_corpus_for_manual(manual_ref, routing_rows=[])
        self.assertEqual(corpus["corpus_source"], "metadata_only")
        self.assertEqual(corpus["nodes"], [])

    def test_lexical_scoring_degrades_to_sparse_only_when_embedding_disabled(self):
        corpus = load_node_corpus_for_manual(
            self._manual_ref(),
            routing_rows=[
                self._row("n1", "Airport Approach"),
                self._row("n2", "Fuel Planning"),
            ],
        )

        result = score_node_corpora(
            "airport approach",
            [corpus],
            top_k=2,
            embedding_mode="auto",
            settings_obj=SimpleNamespace(routing_embeddings_build_mode="disabled"),
        )

        self.assertEqual(result["shortlist"][0]["node_id"], "n1")
        self.assertEqual(result["shortlist"][0]["hybrid_mode"], "sparse_only")
        self.assertEqual(result["dense"]["fallback_reason"], "embedding_build_mode_disabled")
        self.assertEqual(result["shortlist"][0]["lexical_score"], 1.0)

    def test_hybrid_scaffold_uses_dense_scores_only_when_cache_and_provider_are_available(self):
        corpus = load_node_corpus_for_manual(
            self._manual_ref(),
            routing_rows=[
                self._row("n1", "Airport Approach"),
            ],
        )
        result = score_node_corpora(
            "airport approach",
            [corpus],
            top_k=1,
            embedding_mode="auto",
            embedding_config={
                "enabled": True,
                "resolved_mode": "system",
                "provider_source": "system",
                "provider_type": "openai_compatible",
                "model": "openai/text-embedding-3-small",
            },
            dense_scores={"doc_1:ver_1:n1": 0.5},
            settings_obj=SimpleNamespace(routing_embeddings_build_mode="enabled"),
        )

        self.assertTrue(result["dense"]["enabled"])
        self.assertEqual(result["shortlist"][0]["hybrid_mode"], "hybrid")
        self.assertAlmostEqual(result["shortlist"][0]["hybrid_score"], 0.85)

    def test_metrics_cover_outline_final_citation_latency_zero_hit_and_fallback_rates(self):
        row_corpus = load_node_corpus_for_manual(self._manual_ref(), routing_rows=[self._row("n1", "Airport Approach")])
        metadata_corpus = {
            "manual_key": "doc_2:ver_2",
            "manual": {"manual_key": "doc_2:ver_2", "document_id": "doc_2", "version_id": "ver_2"},
            "corpus_source": "metadata_only",
            "nodes": [],
            "node_count": 0,
            "fallback_reason": "node_corpus_unavailable",
            "warning": None,
        }
        result = score_node_corpora(
            "airport approach",
            [row_corpus, metadata_corpus],
            top_k=1,
            embedding_mode="off",
        )

        metrics = evaluate_node_shadow_metrics(
            result,
            outline_diagnostics={
                "manuals": [
                    {
                        "document_id": "doc_1",
                        "version_id": "ver_1",
                        "selected_node_ids": ["n1"],
                    }
                ]
            },
            final_citations=[
                {
                    "document_id": "doc_1",
                    "version_id": "ver_1",
                    "node_id": "n1",
                }
            ],
            retrieve_candidates_latency_ms=20,
            top_k=1,
        )

        self.assertEqual(metrics["node_topk_overlap_with_outline"]["value"], 1.0)
        self.assertEqual(metrics["node_topk_recall_of_final_citation_nodes"]["value"], 1.0)
        self.assertIsNone(metrics["hybrid_vs_lexical_gain"]["value"])
        self.assertEqual(metrics["latency_delta"]["retrieve_candidates_latency_ms"], 20)
        self.assertEqual(metrics["zero_hit_rate"]["value"], 0.0)
        self.assertEqual(metrics["fallback_needed_rate"]["by_source"], {"metadata_only": 1})

    def test_run_node_shadow_replay_accepts_manual_gate_result_without_live_selection_changes(self):
        corpus = load_node_corpus_for_manual(self._manual_ref(), routing_rows=[self._row("n1", "Airport Approach")])
        report = run_node_shadow_replay(
            MagicMock(),
            {
                "question": "airport approach",
                "manual_gate_result": {"applied_manuals": [self._manual_ref()]},
                "top_k": 1,
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
            },
            node_corpora=[corpus],
        )

        self.assertEqual(report["schema_version"], "node_shadow_report_v1")
        self.assertEqual(report["metrics"]["node_topk_recall_of_final_citation_nodes"]["value"], 1.0)
        self.assertEqual(report["shortlist"][0]["node_id"], "n1")

    def test_run_node_shadow_replay_plugs_dense_backend_scores_into_hybrid_scorer(self):
        class FakeDenseBackend:
            def search(self, **_kwargs):
                return NodeDenseSearchResult(
                    dense_scores={
                        "doc_1:ver_1:n1": 0.0,
                        "doc_1:ver_1:n2": 1.0,
                    },
                    dense_source="artifact_exact_scan",
                    requested_dense_source="artifact_exact_scan",
                    enabled=True,
                    query_embedding_dimensions=3,
                    artifacts=[{"uri": "/tmp/bundle.json", "node_count": 2}],
                )

        corpus = load_node_corpus_for_manual(
            self._manual_ref(),
            routing_rows=[
                self._row("n1", "Airport Approach"),
                self._row("n2", "Fuel Planning"),
            ],
        )

        report = run_node_shadow_replay(
            MagicMock(),
            {
                "question": "unrelated query",
                "manual_gate_result": {"applied_manuals": [self._manual_ref()]},
                "top_k": 1,
                "candidate_top_k": 2,
                "embedding_mode": "auto",
                "final_citations": [{"document_id": "doc_1", "version_id": "ver_1", "node_id": "n2"}],
            },
            embedding_config={
                "enabled": True,
                "resolved_mode": "system",
                "provider_source": "system",
                "provider_type": "openai_compatible",
                "model": "openai/text-embedding-3-small",
            },
            dense_search_backend=FakeDenseBackend(),
            node_corpora=[corpus],
            settings_obj=SimpleNamespace(routing_embeddings_build_mode="enabled"),
        )

        self.assertEqual(report["shortlist"][0]["node_id"], "n2")
        self.assertEqual(report["dense"]["dense_source"], "artifact_exact_scan")
        self.assertEqual(report["dense"]["query_embedding_dimensions"], 3)
        self.assertEqual(report["metrics"]["hybrid_vs_lexical_gain"]["value"], 1.0)

    def test_score_node_corpora_preserves_dense_fallback_reason_when_hybrid_enabled(self):
        corpus = load_node_corpus_for_manual(
            self._manual_ref(),
            routing_rows=[
                self._row("n1", "Airport Approach"),
            ],
        )

        result = score_node_corpora(
            "airport approach",
            [corpus],
            embedding_mode="system",
            embedding_config={
                "enabled": True,
                "resolved_mode": "system",
                "provider_source": "system",
                "provider_type": "openai_compatible",
                "model": "text-embedding-test",
            },
            dense_scores={"doc_1:ver_1:n1": 0.9},
            dense_search_metadata={
                "dense_source": "artifact_exact_scan",
                "requested_dense_source": "es_shadow",
                "fallback_reason": "es_index_unavailable",
                "query_embedding_dimensions": 1024,
                "artifact_count": 1,
            },
            settings_obj=SimpleNamespace(routing_embeddings_build_mode="enabled"),
        )

        self.assertEqual(result["dense"]["resolved_mode"], "hybrid")
        self.assertEqual(result["dense"]["fallback_reason"], "es_index_unavailable")
        self.assertEqual(result["dense"]["dense_source"], "artifact_exact_scan")


if __name__ == "__main__":
    unittest.main()
