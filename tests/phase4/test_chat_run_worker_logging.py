import os
import sys
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.services.chat_service import _extract_request_prompt_text, _preview_log_text
from pageindex.utils import _redact_sensitive_data


class TestChatRunWorkerLogging(unittest.TestCase):
    def test_extract_request_prompt_text_reads_last_message_content(self):
        request = {
            "messages": [
                {"role": "system", "content": "ignored"},
                {"role": "user", "content": "final prompt"},
            ]
        }

        prompt = _extract_request_prompt_text(request)

        self.assertEqual(prompt, "final prompt")

    def test_preview_log_text_truncates_long_text(self):
        preview = _preview_log_text("x" * 40, max_chars=10)

        self.assertEqual(preview, "xxxxxxxxxx\n...[truncated]")

    def test_redact_sensitive_data_hides_api_keys_and_tokens(self):
        payload = {
            "api_key": "secret-key",
            "extra_headers": {
                "Authorization": "Bearer secret",
                "X-Api-Key": "abc",
            },
            "nested": {
                "access_token": "token-value",
                "safe": "visible",
            },
        }

        redacted = _redact_sensitive_data(payload)

        self.assertEqual(redacted["api_key"], "***redacted***")
        self.assertEqual(redacted["extra_headers"]["Authorization"], "***redacted***")
        self.assertEqual(redacted["extra_headers"]["X-Api-Key"], "***redacted***")
        self.assertEqual(redacted["nested"]["access_token"], "***redacted***")
        self.assertEqual(redacted["nested"]["safe"], "visible")


if __name__ == "__main__":
    unittest.main()
