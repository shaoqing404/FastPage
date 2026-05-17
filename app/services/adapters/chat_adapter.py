import json
import logging
import time
import urllib.request
import urllib.error
from typing import Iterator

logger = logging.getLogger(__name__)


class DirectChatAdapter:
    """Calls an OpenAI-compatible /chat/completions endpoint directly, without LiteLLM.

    This adapter exists for models that LiteLLM cannot route — customer intranet
    models (LM Studio, Ollama, custom gateways) where the model name isn't in
    LiteLLM's static registry. It sends standard OpenAI chat completion payloads
    over HTTP and supports both streaming and non-streaming responses.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 120.0,
        extra_headers: dict | None = None,
    ):
        url = base_url.rstrip("/")
        if url.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        self.base_url = url
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.extra_headers = dict(extra_headers or {})

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _headers(self, *, accept: str) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": accept,
            **self.extra_headers,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers.pop("Authorization", None)
        return headers

    def completion(self, messages: list[dict], **kwargs) -> dict:
        """Non-streaming completion. Returns the full response dict."""
        payload = {
            "model": self._request_model(),
            "messages": list(messages),
            **kwargs,
        }
        headers = self._headers(accept="application/json")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Chat request failed: {exc.code} {body[:500]}") from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(f"Chat returned non-JSON: {raw[:200]}")
        logger.debug("direct_chat_adapter: model=%s latency_ms=%d", self._request_model(), elapsed_ms)
        return parsed

    def completion_stream(self, messages: list[dict], **kwargs) -> Iterator[dict]:
        """Streaming completion. Yields SSE chunks as parsed dicts."""
        payload = {
            "model": self._request_model(),
            "messages": list(messages),
            "stream": True,
            **kwargs,
        }
        headers = self._headers(accept="text/event-stream")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                for line_bytes in resp:
                    line = line_bytes.decode("utf-8").rstrip("\n\r")
                    if not line or line.startswith(":"):
                        continue
                    if line == "data: [DONE]":
                        break
                    if line.startswith("data: "):
                        try:
                            yield json.loads(line[len("data: "):])
                        except json.JSONDecodeError:
                            continue
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Chat stream failed: {exc.code} {body[:500]}") from exc

    def _request_model(self) -> str:
        for prefix in ("openai/", "litellm/"):
            if self.model.startswith(prefix):
                return self.model[len(prefix):]
        return self.model


def chat_via_adapter(adapter_config: dict, messages: list[dict], **kwargs) -> dict:
    """Convenience: create adapter from config dict and call completion."""
    adapter = DirectChatAdapter(
        base_url=adapter_config["base_url"],
        api_key=adapter_config["api_key"],
        model=adapter_config["model"],
        timeout_seconds=float(adapter_config.get("timeout_seconds", 120)),
        extra_headers=adapter_config.get("extra_headers"),
    )
    return adapter.completion(messages, **kwargs)
