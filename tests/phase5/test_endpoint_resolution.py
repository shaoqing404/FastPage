"""Phase 5.0: test endpoint resolution and probe functions."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.schemas.providers import (
    ModelProviderEndpointCreate,
    ModelProviderEndpointOut,
    ModelProviderEndpointUpdate,
    ProbeRuntimeDraftRequest,
    ProbeRuntimeRequest,
    ProbeRuntimeResult,
)
from app.services.provider_service import (
    _endpoint_config,
    _sanitize_upstream_error,
    _endpoint_id,
    _request_headers,
    _sync_provider_endpoints,
    resolve_chat_config,
)


class TestSanitizeUpstreamError(unittest.TestCase):
    def test_redacts_bearer_token(self):
        raw = '401 Unauthorized: {"error":"Invalid Bearer sk-abc123def456"}'
        result = _sanitize_upstream_error(raw)
        self.assertNotIn("sk-abc123def456", result)
        self.assertIn("[REDACTED]", result)

    def test_redacts_api_key_in_json(self):
        raw = '{"api_key": "secret-key-value", "error": "unauthorized"}'
        result = _sanitize_upstream_error(raw)
        self.assertNotIn("secret-key-value", result)
        self.assertIn("[REDACTED]", result)

    def test_truncates_long_errors(self):
        raw = "x" * 500
        result = _sanitize_upstream_error(raw, max_len=100)
        self.assertLess(len(result), 120)
        self.assertIn("...(truncated)", result)

    def test_preserves_harmless_text(self):
        raw = "Connection timeout after 30 seconds"
        result = _sanitize_upstream_error(raw)
        self.assertEqual(raw, result)


class TestEndpointId(unittest.TestCase):
    def test_generates_predictable_id(self):
        eid = _endpoint_id("prov-123", "chat")
        self.assertIn("prov-123", eid)
        self.assertIn("chat", eid)

    def test_truncated_to_64_chars(self):
        eid = _endpoint_id("x" * 80, "embedding")
        self.assertLessEqual(len(eid), 64)


class TestEndpointConfig(unittest.TestCase):
    def test_request_headers_omit_authorization_for_no_auth(self):
        headers = _request_headers("", extra_headers={"X-Test": "ok", "Authorization": "Bearer stale"})
        self.assertNotIn("Authorization", headers)
        self.assertEqual(headers["X-Test"], "ok")

    def test_request_headers_include_authorization_when_key_present(self):
        headers = _request_headers("sk-test")
        self.assertEqual(headers["Authorization"], "Bearer sk-test")

    def test_returns_expected_keys(self):
        ep = MagicMock()
        ep.adapter = "openai_embedding"
        ep.base_url = "https://example.com/v1"
        ep.model = "text-embedding-3-small"
        ep.api_key_encrypted = None
        ep.extra_headers_json = "{}"
        ep.config_json = '{"batch_size": 32}'
        ep.id = "endpoint-1"
        provider_config = {"api_key": "provider-key"}

        from app.core.config import get_settings

        with patch.object(
            get_settings(), "secret_key", new="test-secret-key-for-unit-tests-only"
        ):
            result = _endpoint_config(ep, provider_config)
        self.assertTrue(result["enabled"])
        self.assertEqual(result["resolved_mode"], "provider_endpoint")
        self.assertEqual(result["model"], "text-embedding-3-small")
        self.assertEqual(result["base_url"], "https://example.com/v1")
        self.assertEqual(result["adapter"], "openai_embedding")
        self.assertEqual(result["provider_type"], "openai_embedding")
        self.assertEqual(result["api_key"], "provider-key")
        self.assertEqual(result["config"], {"batch_size": 32})
        self.assertEqual(result["endpoint_id"], "endpoint-1")

    def test_resolve_chat_config_prefers_enabled_endpoint(self):
        ep = MagicMock()
        ep.adapter = "openai_chat"
        ep.base_url = "https://chat.example.com/v1/chat/completions"
        ep.model = "qwen3.5-35b-a3b"
        ep.api_key_encrypted = None
        ep.extra_headers_json = "{}"
        ep.config_json = "{}"
        ep.id = "chat-endpoint-1"
        db = MagicMock()
        db.scalars.return_value.first.return_value = ep

        result = resolve_chat_config(
            provider_config={
                "provider_id": "provider-1",
                "base_url": "https://provider.example.com/v1",
                "api_key": "provider-key",
                "default_model": "openai/provider-default",
                "extra_headers": {},
            },
            db=db,
            tenant_id="tenant-1",
            workspace_id="workspace-1",
        )

        self.assertEqual(result["base_url"], "https://chat.example.com/v1/chat/completions")
        self.assertEqual(result["model"], "qwen3.5-35b-a3b")
        self.assertEqual(result["adapter"], "openai_chat")
        self.assertEqual(result["endpoint_id"], "chat-endpoint-1")

    def test_sync_endpoint_without_key_keeps_dynamic_provider_inheritance(self):
        db = MagicMock()
        db.scalars.return_value.first.return_value = None
        provider = SimpleNamespace(
            id="provider-1",
            base_url="https://provider.example.com/v1",
            default_model="qwen3.5-35b-a3b",
        )
        payload = SimpleNamespace(
            id=None,
            capability="chat",
            adapter="openai_chat",
            base_url="https://chat.example.com/v1/chat/completions",
            model="qwen3.5-35b-a3b",
            api_key=None,
            extra_headers={},
            config={},
            enabled=True,
            is_default=True,
        )

        _sync_provider_endpoints(db, provider, [payload])

        endpoint = db.add.call_args.args[0]
        self.assertIsNone(endpoint.api_key_encrypted)


class TestProbeSchemas(unittest.TestCase):
    def test_probe_runtime_request_defaults(self):
        req = ProbeRuntimeRequest()
        self.assertIsNone(req.capability)
        self.assertIsNone(req.endpoint_id)

    def test_probe_draft_request_minimal(self):
        req = ProbeRuntimeDraftRequest(
            provider_type="openai_compatible",
            base_url="https://example.com/v1",
            api_key="",
            endpoints=[
                ModelProviderEndpointCreate(
                    capability="chat",
                    adapter="openai_chat",
                    base_url="https://example.com/v1",
                    model="gpt-4",
                )
            ],
        )
        self.assertEqual(len(req.endpoints), 1)
        self.assertEqual(req.endpoints[0].capability, "chat")
        self.assertEqual(req.api_key, "")

    def test_probe_runtime_result_shape(self):
        result = ProbeRuntimeResult(
            capability="embedding",
            adapter="openai_embedding",
            model="text-embedding-3-small",
            status="healthy",
            latency_ms=150,
            dimensions=1536,
        )
        data = result.model_dump()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["dimensions"], 1536)


if __name__ == "__main__":
    unittest.main()
