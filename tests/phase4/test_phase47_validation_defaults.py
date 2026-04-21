import unittest
from types import SimpleNamespace
from unittest.mock import patch

from spec.fastapi_service.phase4_access_and_admin_control_plane import phase4_7_backend_validation as validation


class TestPhase47ValidationDefaults(unittest.TestCase):
    def test_default_pdf_uses_repo_local_examples_document(self):
        expected_root = (validation.ROOT / "examples" / "documents").resolve()
        default_pdf = validation.DEFAULT_PDF.resolve()

        self.assertTrue(default_pdf.exists())
        self.assertEqual(default_pdf.parent, expected_root)
        self.assertEqual(default_pdf.name, "attention-residuals.pdf")
        self.assertEqual(default_pdf.suffix.lower(), ".pdf")

    def test_load_runtime_defaults_uses_env_compatible_provider_settings(self):
        settings = SimpleNamespace(
            llm_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            llm_api_key="phase47-test-key",
        )

        with (
            patch.object(validation, "get_settings", return_value=settings),
            patch.object(validation, "default_llm_model", return_value="openai/qwen-plus"),
        ):
            defaults = validation.load_runtime_defaults()

        self.assertEqual(
            defaults,
            {
                "provider_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "provider_api_key": "phase47-test-key",
                "provider_model": "openai/qwen-plus",
            },
        )

    def test_load_runtime_defaults_requires_api_key_and_base_url(self):
        settings = SimpleNamespace(
            llm_base_url="",
            llm_api_key="",
        )

        with patch.object(validation, "get_settings", return_value=settings):
            with self.assertRaises(validation.ValidationError):
                validation.load_runtime_defaults()
