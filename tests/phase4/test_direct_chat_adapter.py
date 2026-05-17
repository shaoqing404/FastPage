import unittest

from app.services.adapters.chat_adapter import DirectChatAdapter
from app.services.adapters.rerank_adapter import GenericRerankAdapter


class TestDirectChatAdapterModelNormalization(unittest.TestCase):
    def test_strips_only_historical_routing_hints(self):
        cases = [
            ("openai/qwen3.5-35b-a3b", "qwen3.5-35b-a3b"),
            ("litellm/qwen3.5-35b-a3b", "qwen3.5-35b-a3b"),
            ("zai/glm-4.7-flash", "zai/glm-4.7-flash"),
            ("custom/vendor/model", "custom/vendor/model"),
            ("Qwen3-Embedding-8B", "Qwen3-Embedding-8B"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                adapter = DirectChatAdapter(
                    base_url="https://example.com/v1",
                    api_key="test-key",
                    model=raw,
                )
                self.assertEqual(adapter._request_model(), expected)

    def test_empty_api_key_omits_authorization_header(self):
        adapter = DirectChatAdapter(
            base_url="https://example.com/v1",
            api_key="",
            model="qwen3.6-plus",
            extra_headers={"Authorization": "Bearer stale"},
        )
        headers = adapter._headers(accept="application/json")
        self.assertNotIn("Authorization", headers)

    def test_rerank_empty_api_key_omits_authorization_header(self):
        adapter = GenericRerankAdapter(
            base_url="https://example.com/v1",
            api_key="",
            model="bge-reranker-v2-m3",
            extra_headers={"Authorization": "Bearer stale"},
        )
        headers = adapter._headers()
        self.assertNotIn("Authorization", headers)


if __name__ == "__main__":
    unittest.main()
