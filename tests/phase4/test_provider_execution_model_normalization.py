import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services.provider_service import normalize_execution_model


class TestProviderExecutionModelNormalization(unittest.TestCase):
    def test_openai_compatible_models_are_prefixed(self):
        self.assertEqual(
            normalize_execution_model("openai_compatible", "qwen3.5-plus"),
            "openai/qwen3.5-plus",
        )

    def test_openai_compatible_namespaced_models_keep_openai_prefix_only_once(self):
        self.assertEqual(
            normalize_execution_model("openai_compatible", "MiniMax/MiniMax-M2.7"),
            "openai/MiniMax/MiniMax-M2.7",
        )
        self.assertEqual(
            normalize_execution_model("openai_compatible", "openai/qwen-plus"),
            "openai/qwen-plus",
        )

    def test_other_provider_types_preserve_model_name(self):
        self.assertEqual(
            normalize_execution_model("system_default", "openai/qwen-plus"),
            "openai/qwen-plus",
        )


if __name__ == "__main__":
    unittest.main()
