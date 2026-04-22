import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.errors import AppError, ErrorCode
from app.services.provider_service import (
    normalize_execution_model,
    normalized_supported_execution_models,
    validate_provider_model_selection,
)


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

    def test_supported_models_are_normalized_into_execution_namespace(self):
        self.assertEqual(
            normalized_supported_execution_models(
                "openai_compatible",
                "qwen3-plus",
                ["qwen3-plus", "openai/qwen3-plus", "qwen3.5-plus"],
            ),
            ["openai/qwen3-plus", "openai/qwen3.5-plus"],
        )

    def test_validate_provider_model_selection_rejects_unsupported_pair(self):
        with self.assertRaises(AppError) as ctx:
            validate_provider_model_selection(
                provider_id="provider_1",
                provider_type="openai_compatible",
                provider_name="Tenant OpenAI Compatible",
                default_model="qwen3-plus",
                supported_models=["qwen3-plus", "qwen3.5-plus"],
                model="gpt-4o",
                subject="Skill model",
            )

        self.assertEqual(ctx.exception.code, ErrorCode.PROVIDER_MODEL_UNSUPPORTED)
        self.assertIn('Skill model "gpt-4o"', ctx.exception.message)
        self.assertIn('qwen3-plus', ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
