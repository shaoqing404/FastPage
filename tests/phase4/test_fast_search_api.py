import unittest
from unittest.mock import MagicMock, patch

from app.schemas.search import FastSearchRequest
from app.services.node_shadow_service import run_fast_search

class TestFastSearchApi(unittest.TestCase):
    def test_schema_bounds(self):
        # test default
        req = FastSearchRequest(document_id="d1", version_id="v1", query="test")
        self.assertEqual(req.node_top_k, 3)
        self.assertTrue(req.include_snippets)

        # test valid bounds
        req_1 = FastSearchRequest(document_id="d1", version_id="v1", query="test", node_top_k=1)
        self.assertEqual(req_1.node_top_k, 1)

        req_10 = FastSearchRequest(document_id="d1", version_id="v1", query="test", node_top_k=10)
        self.assertEqual(req_10.node_top_k, 10)

    def test_complex_query_boundary_flag(self):
        mock_document = MagicMock()
        mock_version = MagicMock()
        mock_db = MagicMock()

        with patch("app.services.node_shadow_service.build_node_corpora") as mock_build, \
             patch("app.services.node_shadow_service.score_node_corpora") as mock_score:
            
            mock_score.return_value = {
                "dense": {"resolved_mode": "hybrid"},
                "node_shadow_latency_ms": 100,
                "shortlist": []
            }

            result = run_fast_search(
                db=mock_db,
                principal=MagicMock(),
                document=mock_document,
                version=mock_version,
                query="能否在雨夜降落？"
            )

            self.assertTrue(result["boundary_flags"])
            self.assertEqual(result["fallback_recommendation"], "建议使用 DeepResearch")

    def test_fallback_reason(self):
        mock_document = MagicMock()
        mock_version = MagicMock()
        mock_db = MagicMock()

        with patch("app.services.node_shadow_service.build_node_corpora") as mock_build, \
             patch("app.services.node_shadow_service.score_node_corpora") as mock_score:
            
            mock_score.return_value = {
                "dense": {
                    "resolved_mode": "sparse_only",
                    "fallback_reason": "embedding_unavailable"
                },
                "node_shadow_latency_ms": 100,
                "shortlist": []
            }

            result = run_fast_search(
                db=mock_db,
                principal=MagicMock(),
                document=mock_document,
                version=mock_version,
                query="特殊机场"
            )

            self.assertFalse(result["boundary_flags"])
            self.assertEqual(result["fallback_recommendation"], "FastSearch data not ready; use DeepResearch or rebuild fast index")
            self.assertEqual(result["fallback_reason"], "embedding_unavailable")

    def test_fast_search_success(self):
        mock_document = MagicMock()
        mock_version = MagicMock()
        mock_db = MagicMock()

        with patch("app.services.node_shadow_service.build_node_corpora") as mock_build, \
             patch("app.services.node_shadow_service.score_node_corpora") as mock_score:
            
            mock_score.return_value = {
                "dense": {
                    "resolved_mode": "hybrid",
                },
                "node_shadow_latency_ms": 150,
                "shortlist": [
                    {
                        "node_id": "001",
                        "title": "特殊机场",
                        "page_start": 5,
                        "page_end": 6,
                        "hybrid_score": 0.95,
                        "corpus_source": "document_routing_nodes",
                        "route_summary": "特殊机场列表..."
                    }
                ]
            }

            result = run_fast_search(
                db=mock_db,
                principal=MagicMock(),
                document=mock_document,
                version=mock_version,
                query="特殊机场有哪些"
            )

            self.assertEqual(result["mode"], "hybrid")
            self.assertEqual(result["legacy_node_shadow_latency_ms"], 150)
            self.assertEqual(len(result["nodes"]), 1)
            self.assertEqual(result["nodes"][0]["node_id"], "001")
            self.assertEqual(result["nodes"][0]["snippet"], "特殊机场列表...")

if __name__ == "__main__":
    unittest.main()
