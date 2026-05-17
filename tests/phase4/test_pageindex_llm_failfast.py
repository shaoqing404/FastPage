import os
import sys
import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DATA_DIR", "/tmp/pageindex-test-data")
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())

from pageindex.utils import count_tokens, get_page_tokens, is_fatal_llm_model_error, llm_acompletion, llm_completion


class TestPageIndexLlmFailFast(unittest.TestCase):
    def test_fatal_model_error_detector_matches_model_not_found_signals(self):
        self.assertTrue(is_fatal_llm_model_error("openai.NotFoundError: model_not_found"))
        self.assertTrue(is_fatal_llm_model_error("unsupported model 'openai/qwen3-plus'"))
        self.assertFalse(is_fatal_llm_model_error("connection reset by peer"))

    @patch(
        "pageindex.utils._load_llm_runtime_config",
        return_value={
            "enable_litellm": False,
            "base_url": "http://runtime.example/v1",
            "api_key": "",
            "model": "openai/qwen3-plus",
        },
    )
    @patch("pageindex.utils.litellm.completion", side_effect=AssertionError("LiteLLM should not be called"))
    @patch("app.services.adapters.chat_adapter.DirectChatAdapter")
    def test_llm_completion_defaults_to_direct_adapter(self, mock_adapter_class, _mock_litellm, _mock_runtime):
        mock_adapter_class.return_value.completion.return_value = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        }
        stats_events = []

        result = llm_completion(
            model="openai/qwen3-plus",
            prompt="hello",
            request_options={
                "api_base": "http://custom.example/v1",
                "api_key": "",
                "extra_headers": {"X-Test": "1"},
                "temperature": 0.2,
                "provider_type": "openai_compatible",
            },
            stats_hook=stats_events.append,
        )

        self.assertEqual(result, "ok")
        mock_adapter_class.assert_called_once_with(
            base_url="http://custom.example/v1",
            api_key="",
            model="openai/qwen3-plus",
            timeout_seconds=120.0,
            extra_headers={"X-Test": "1"},
        )
        _, completion_kwargs = mock_adapter_class.return_value.completion.call_args
        self.assertEqual(completion_kwargs["temperature"], 0.2)
        self.assertNotIn("api_base", completion_kwargs)
        self.assertNotIn("api_key", completion_kwargs)
        self.assertNotIn("extra_headers", completion_kwargs)
        self.assertNotIn("provider_type", completion_kwargs)
        self.assertEqual(stats_events[0]["usage"]["total_tokens"], 4)

    @patch(
        "pageindex.utils._load_llm_runtime_config",
        return_value={
            "enable_litellm": True,
            "base_url": "http://runtime.example/v1",
            "api_key": "key",
            "model": "openai/qwen3-plus",
        },
    )
    @patch("app.services.adapters.chat_adapter.DirectChatAdapter", side_effect=AssertionError("Direct should be disabled"))
    @patch("pageindex.utils.litellm.completion")
    def test_enable_litellm_uses_legacy_completion(self, mock_completion, _mock_adapter, _mock_runtime):
        mock_completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="legacy"), finish_reason="stop")],
            usage={"total_tokens": 1},
        )

        result = llm_completion(model="litellm/qwen3-plus", prompt="hello")

        self.assertEqual(result, "legacy")
        mock_completion.assert_called_once()
        self.assertEqual(mock_completion.call_args.kwargs["model"], "qwen3-plus")

    @patch(
        "pageindex.utils._load_llm_runtime_config",
        return_value={
            "enable_litellm": False,
            "base_url": "http://runtime.example/v1",
            "api_key": "",
            "model": "openai/qwen3-plus",
        },
    )
    @patch("app.services.adapters.chat_adapter.DirectChatAdapter")
    def test_llm_acompletion_uses_direct_without_blocking_event_loop(self, mock_adapter_class, _mock_runtime):
        mock_adapter_class.return_value.completion.return_value = {
            "choices": [{"message": {"content": "async ok"}, "finish_reason": "stop"}],
        }

        result = asyncio.run(llm_acompletion(model="openai/qwen3-plus", prompt="hello"))

        self.assertEqual(result, "async ok")
        mock_adapter_class.return_value.completion.assert_called_once()

    @patch("pageindex.utils.litellm.token_counter", side_effect=AssertionError("LiteLLM token_counter should not be called"))
    def test_count_tokens_does_not_call_litellm_token_counter(self, _mock_token_counter):
        self.assertGreater(count_tokens("hello world", model="openai/qwen3-plus"), 0)

    @patch("pageindex.utils.litellm.token_counter", side_effect=AssertionError("LiteLLM token_counter should not be called"))
    @patch("pageindex.utils.PyPDF2.PdfReader")
    def test_get_page_tokens_does_not_call_litellm_token_counter(self, mock_pdf_reader, _mock_token_counter):
        class FakePage:
            def __init__(self, text: str) -> None:
                self._text = text

            def extract_text(self) -> str:
                return self._text

        mock_pdf_reader.return_value.pages = [FakePage("alpha"), FakePage("beta")]

        result = get_page_tokens("/tmp/fake.pdf", model="openai/qwen3-plus")

        self.assertEqual([page_text for page_text, _ in result], ["alpha", "beta"])
        self.assertTrue(all(token_count > 0 for _, token_count in result))

    @patch("pageindex.utils.time.sleep")
    @patch(
        "pageindex.utils._load_llm_runtime_config",
        return_value={
            "enable_litellm": True,
            "base_url": "http://runtime.example/v1",
            "api_key": "key",
            "model": "openai/qwen3-plus",
        },
    )
    @patch("pageindex.utils.litellm.completion")
    def test_llm_completion_does_not_retry_fatal_model_errors(self, mock_completion, _mock_runtime, mock_sleep):
        mock_completion.side_effect = RuntimeError("openai.NotFoundError: model_not_found")

        with self.assertRaises(RuntimeError) as ctx:
            llm_completion(model="openai/qwen3-plus", prompt="hello")

        self.assertIn("Fatal model configuration error", str(ctx.exception))
        self.assertEqual(mock_completion.call_count, 1)
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
