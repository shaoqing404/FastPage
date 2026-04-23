import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.services.runtime_observation_service import sanitize_observation_payload


class TestRuntimeObservationSerialization(unittest.TestCase):
    def test_sanitize_observation_payload_encodes_nested_datetimes(self):
        created_at = datetime(2026, 4, 22, 16, 8, 34)

        payload = sanitize_observation_payload(
            {
                "created_at": created_at,
                "nested": {
                    "finished_at": created_at,
                },
            }
        )

        self.assertEqual(payload["created_at"], created_at.isoformat())
        self.assertEqual(payload["nested"]["finished_at"], created_at.isoformat())


if __name__ == "__main__":
    unittest.main()
