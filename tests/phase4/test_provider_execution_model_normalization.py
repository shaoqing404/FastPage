import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Simulate a developer .env that has already cached non-local storage before
# parse pipeline tests import parse_service in the same unittest process.
os.environ.setdefault("STORAGE_BACKEND", "minio")

from app.core.errors import AppError, ErrorCode
import app.services.provider_service as provider_service
from app.services.provider_service import (
    classify_provider_capabilities,
    normalize_execution_model,
    normalize_rerank_provider_type,
    normalized_supported_execution_models,
    resolve_embedding_config,
    resolve_rerank_config,
    resolve_system_embedding_config,
    validate_provider_model_selection,
)


def _embedding_settings(
    *,
    enabled: bool = True,
    base_url: str = "https://example.com/v1",
    api_key: str = "system-embedding-secret",
    model: str = "text-embedding-3-large",
    provider_type: str = "openai_compatible",
):
    return SimpleNamespace(
        system_embedding_enabled=enabled,
        system_embedding_base_url=base_url,
        system_embedding_api_key=api_key,
        system_embedding_model=model,
        system_embedding_provider_type=provider_type,
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

    def test_resolve_rerank_config_normalizes_openai_compatible_model(self):
        rerank_config = resolve_rerank_config(
            provider_config={
                "provider_type": "openai_compatible",
                "base_url": "https://example.com/v1",
                "api_key": "secret",
                "capabilities": {
                    "rerank_models": ["qwen3-vl-rerank"],
                    "default_rerank_model": "qwen3-vl-rerank",
                },
            },
            rerank_mode="provider",
        )

        self.assertTrue(rerank_config["enabled"])
        self.assertEqual(rerank_config["resolved_mode"], "provider")
        self.assertEqual(rerank_config["model"], "openai/qwen3-vl-rerank")

    def test_native_rerank_base_url_switches_provider_type(self):
        self.assertEqual(
            normalize_rerank_provider_type(
                "openai_compatible",
                "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
            ),
            "dashscope_rerank",
        )

    def test_classify_provider_capabilities_detects_embedding_models(self):
        capabilities = classify_provider_capabilities(
            "gpt-4o",
            [
                "text-embedding-3-large",
                "bge-reranker-v2-m3",
                "gpt-4o-mini",
            ],
        )

        self.assertEqual(capabilities["chat_models"], ["gpt-4o", "gpt-4o-mini"])
        self.assertEqual(capabilities["rerank_models"], ["bge-reranker-v2-m3"])
        self.assertEqual(capabilities["embedding_models"], ["text-embedding-3-large"])
        self.assertEqual(capabilities["default_embedding_model"], "text-embedding-3-large")

    def test_resolve_system_embedding_config_is_disabled_when_feature_off(self):
        with patch.object(provider_service, "settings", _embedding_settings(enabled=False)):
            embedding_config = resolve_system_embedding_config()

        self.assertFalse(embedding_config["enabled"])
        self.assertEqual(embedding_config["source"], "disabled")

    def test_resolve_system_embedding_config_is_disabled_when_api_key_missing(self):
        with patch.object(provider_service, "settings", _embedding_settings(api_key="")):
            embedding_config = resolve_system_embedding_config()

        self.assertFalse(embedding_config["enabled"])
        self.assertEqual(embedding_config["source"], "disabled")

    def test_resolve_system_embedding_config_is_disabled_when_model_missing(self):
        with patch.object(provider_service, "settings", _embedding_settings(model="")):
            embedding_config = resolve_system_embedding_config()

        self.assertFalse(embedding_config["enabled"])
        self.assertEqual(embedding_config["source"], "disabled")

    def test_resolve_system_embedding_config_uses_complete_config(self):
        with patch.object(provider_service, "settings", _embedding_settings()):
            embedding_config = resolve_system_embedding_config()

        self.assertTrue(embedding_config["enabled"])
        self.assertEqual(embedding_config["source"], "system")
        self.assertEqual(embedding_config["provider_type"], "openai_compatible")
        self.assertEqual(embedding_config["model"], "text-embedding-3-large")

    def test_resolve_embedding_config_falls_back_to_system_embedding(self):
        provider_config = {
            "provider_type": "openai_compatible",
            "base_url": "https://example.com/v1",
            "api_key": "provider-secret",
            "capabilities": {
                "embedding_models": [],
                "default_embedding_model": None,
            },
        }

        with patch.object(provider_service, "settings", _embedding_settings()):
            embedding_config = resolve_embedding_config(
                provider_config=provider_config,
                embedding_mode="auto",
            )

        self.assertTrue(embedding_config["enabled"])
        self.assertEqual(embedding_config["resolved_mode"], "system")
        self.assertEqual(embedding_config["provider_source"], "system")
        self.assertEqual(embedding_config["model"], "openai/text-embedding-3-large")
        self.assertEqual(embedding_config["fallback_reason"], "provider_embedding_unavailable")

    def test_resolve_embedding_config_off_disables_embedding(self):
        provider_config = {
            "provider_type": "openai_compatible",
            "base_url": "https://example.com/v1",
            "api_key": "provider-secret",
            "capabilities": {
                "embedding_models": ["text-embedding-3-small"],
                "default_embedding_model": "text-embedding-3-small",
            },
        }

        with patch.object(provider_service, "settings", _embedding_settings()):
            embedding_config = resolve_embedding_config(
                provider_config=provider_config,
                embedding_mode="off",
            )

        self.assertFalse(embedding_config["enabled"])
        self.assertEqual(embedding_config["resolved_mode"], "off")
        self.assertIsNone(embedding_config["model"])
        self.assertEqual(embedding_config["fallback_reason"], "disabled_by_flag")

    def test_resolve_embedding_config_defaults_to_disabled_dark_contract(self):
        provider_config = {
            "provider_type": "openai_compatible",
            "base_url": "https://provider.example/v1",
            "api_key": "provider-secret",
            "capabilities": {
                "embedding_models": ["text-embedding-3-small"],
                "default_embedding_model": "text-embedding-3-small",
            },
        }

        with patch.object(provider_service, "settings", _embedding_settings()):
            embedding_config = resolve_embedding_config(
                provider_config=provider_config,
                embedding_mode=None,
            )

        self.assertFalse(embedding_config["enabled"])
        self.assertEqual(embedding_config["resolved_mode"], "off")
        self.assertIsNone(embedding_config["provider_source"])
        self.assertIsNone(embedding_config["model"])
        self.assertEqual(embedding_config["fallback_reason"], "disabled_by_flag")

    def test_resolve_embedding_config_invalid_mode_stays_disabled(self):
        provider_config = {
            "provider_type": "openai_compatible",
            "base_url": "https://provider.example/v1",
            "api_key": "provider-secret",
            "capabilities": {
                "embedding_models": ["text-embedding-3-small"],
                "default_embedding_model": "text-embedding-3-small",
            },
        }

        with patch.object(provider_service, "settings", _embedding_settings()):
            embedding_config = resolve_embedding_config(
                provider_config=provider_config,
                embedding_mode="unexpected",
            )

        self.assertFalse(embedding_config["enabled"])
        self.assertEqual(embedding_config["resolved_mode"], "off")
        self.assertIsNone(embedding_config["provider_source"])
        self.assertIsNone(embedding_config["model"])
        self.assertEqual(embedding_config["fallback_reason"], "invalid_mode_disabled")

    def test_resolve_embedding_config_prefers_provider_embedding(self):
        provider_config = {
            "provider_type": "openai_compatible",
            "base_url": "https://provider.example/v1",
            "api_key": "provider-secret",
            "capabilities": {
                "embedding_models": ["text-embedding-3-small"],
                "default_embedding_model": "text-embedding-3-small",
            },
        }

        with patch.object(provider_service, "settings", _embedding_settings(enabled=False)):
            embedding_config = resolve_embedding_config(
                provider_config=provider_config,
                embedding_mode="auto",
            )

        self.assertTrue(embedding_config["enabled"])
        self.assertEqual(embedding_config["resolved_mode"], "provider")
        self.assertEqual(embedding_config["provider_source"], "provider")
        self.assertEqual(embedding_config["model"], "openai/text-embedding-3-small")
        self.assertIsNone(embedding_config["fallback_reason"])


if __name__ == "__main__":
    unittest.main()
