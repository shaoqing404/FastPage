import unittest

from app.services.adapters.chat_adapter import DirectChatAdapter


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


if __name__ == "__main__":
    unittest.main()
