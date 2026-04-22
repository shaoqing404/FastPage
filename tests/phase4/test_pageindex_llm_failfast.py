import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())

from pageindex.utils import is_fatal_llm_model_error, llm_completion


class TestPageIndexLlmFailFast(unittest.TestCase):
    def test_fatal_model_error_detector_matches_model_not_found_signals(self):
        self.assertTrue(is_fatal_llm_model_error("openai.NotFoundError: model_not_found"))
        self.assertTrue(is_fatal_llm_model_error("unsupported model 'openai/qwen3-plus'"))
        self.assertFalse(is_fatal_llm_model_error("connection reset by peer"))

    @patch("pageindex.utils.time.sleep")
    @patch("pageindex.utils.litellm.completion")
    def test_llm_completion_does_not_retry_fatal_model_errors(self, mock_completion, mock_sleep):
        mock_completion.side_effect = RuntimeError("openai.NotFoundError: model_not_found")

        with self.assertRaises(RuntimeError) as ctx:
            llm_completion(model="openai/qwen3-plus", prompt="hello")

        self.assertIn("Fatal model configuration error", str(ctx.exception))
        self.assertEqual(mock_completion.call_count, 1)
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
