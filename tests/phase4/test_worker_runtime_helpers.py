import os
import sys
import unittest
from unittest.mock import MagicMock, mock_open, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.worker import _build_worker_heartbeat_payload, _current_rss_bytes, _worker_node_code_with_pid, _worker_registry_key


class TestWorkerRuntimeHelpers(unittest.TestCase):
    def test_worker_node_code_with_pid_appends_pid_once(self):
        code = _worker_node_code_with_pid("worker:host-a", 4321)

        self.assertEqual(code, "worker:host-a:pid4321")
        self.assertEqual(_worker_node_code_with_pid(code, 4321), code)

    def test_worker_registry_key_uses_configured_prefix(self):
        key = _worker_registry_key("worker:host-a:pid4321")

        self.assertTrue(key.endswith(":worker:host-a:pid4321"))
        self.assertIn("pageindex:workers", key)

    def test_worker_heartbeat_payload_marks_busy_and_keeps_job_context(self):
        payload = _build_worker_heartbeat_payload(
            worker_node_code="worker:host-a:pid4321",
            pid=4321,
            queue_names=["pageindex:chat", "pageindex:parse"],
            started_at="2026-04-22T10:00:00Z",
            current_job={"kind": "chat_run", "run_id": "run_1"},
            queue_backlogs={"pageindex:chat": 3},
            connection_state="connected",
        )

        self.assertEqual(payload["status"], "busy")
        self.assertEqual(payload["current_job"]["run_id"], "run_1")
        self.assertEqual(payload["queue_backlogs"]["pageindex:chat"], 3)
        self.assertEqual(payload["connection_state"], "connected")

    @patch("app.worker.open", new_callable=mock_open, read_data="Name:\tpython\nVmRSS:\t2048 kB\n")
    def test_current_rss_prefers_linux_vmrss(self, mocked_open):
        rss_bytes, source = _current_rss_bytes()

        self.assertEqual(rss_bytes, 2048 * 1024)
        self.assertEqual(source, "proc_status_vmrss")
        mocked_open.assert_called_once_with("/proc/self/status", "r", encoding="utf-8")

    @patch("app.worker._fallback_rss_bytes", return_value=(1234, "ru_maxrss"))
    @patch("app.worker.open", side_effect=FileNotFoundError)
    def test_current_rss_falls_back_when_procfs_missing(self, mocked_open, mocked_fallback):
        rss_bytes, source = _current_rss_bytes()

        self.assertEqual((rss_bytes, source), (1234, "ru_maxrss"))
        self.assertEqual(mocked_open.call_count, 2)
        mocked_fallback.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
