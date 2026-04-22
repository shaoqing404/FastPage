import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.services.pageindex_service import rerank_candidates


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestPageIndexNativeRerank(unittest.TestCase):
    def test_native_rerank_endpoint_is_used_without_chat_completions_suffix(self):
        candidates = [
            {
                "candidate_id": "cand_1",
                "document_label": "manual-a.pdf",
                "title": "Section A",
                "page_start": 10,
                "page_end": 12,
            },
            {
                "candidate_id": "cand_2",
                "document_label": "manual-b.pdf",
                "title": "Section B",
                "page_start": 20,
                "page_end": 21,
            },
        ]
        seen = {}

        def fake_urlopen(request_obj, timeout=0):
            seen["url"] = request_obj.full_url
            seen["body"] = json.loads(request_obj.data.decode("utf-8"))
            return _FakeResponse(
                {
                    "output": {
                        "results": [
                            {"index": 1, "relevance_score": 0.91},
                            {"index": 0, "relevance_score": 0.54},
                        ]
                    }
                }
            )

        with patch("urllib.request.urlopen", side_effect=fake_urlopen) as mocked_urlopen:
            ranked, meta = rerank_candidates(
                "航空公司有多少个特殊机场",
                candidates,
                "qwen3-vl-rerank",
                request_options={
                    "api_base": "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
                    "api_key": "secret",
                    "provider_type": "dashscope_rerank",
                },
                top_k=2,
            )

        self.assertEqual(mocked_urlopen.call_count, 1)
        self.assertEqual(
            seen["url"],
            "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
        )
        self.assertEqual(seen["body"]["model"], "qwen3-vl-rerank")
        self.assertEqual(len(seen["body"]["input"]["documents"]), 2)
        self.assertTrue(meta["applied"])
        self.assertEqual(meta["mode"], "native_rerank")
        self.assertEqual(ranked[0]["candidate_id"], "cand_2")
        self.assertEqual(ranked[0]["rerank_score"], 0.91)


if __name__ == "__main__":
    unittest.main()
