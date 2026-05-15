import json
import logging
import time
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


class GenericRerankAdapter:
    """Calls a standard /rerank endpoint with {model, query, documents, top_n}.

    Expected response shape:
      {"results": [{"index": 0, "relevance_score": 0.95}, ...]}

    This adapter supports any OpenAI-compatible rerank endpoint, including
    customer intranet deployments where chat/embedding/rerank are separate URLs.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 60.0,
        extra_headers: dict | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.extra_headers = dict(extra_headers or {})

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/rerank"):
            return self.base_url
        return f"{self.base_url}/rerank"

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int = 8,
    ) -> list[dict]:
        """Return ranked results: [{"index": int, "score": float}, ...]."""
        payload = {
            "model": self.model,
            "query": query,
            "documents": list(documents),
            "top_n": min(top_n, len(documents)),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            **self.extra_headers,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Rerank request failed: {exc.code} {body[:500]}") from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(f"Rerank returned non-JSON response: {raw[:200]}")
        results = parsed.get("results") if isinstance(parsed, dict) else None
        if not isinstance(results, list):
            raise RuntimeError(f"Rerank response missing 'results' list: {raw[:200]}")
        ranked: list[dict] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index", item.get("document_index", -1)))
            except (TypeError, ValueError):
                continue
            try:
                score = float(item.get("relevance_score", item.get("score", 0.0)))
            except (TypeError, ValueError):
                score = 0.0
            ranked.append({"index": index, "score": max(0.0, min(score, 1.0))})
            if len(ranked) >= top_n:
                break
        logger.info(
            "rerank_adapter: model=%s docs=%d top_n=%d latency_ms=%d results=%d",
            self.model, len(documents), top_n, elapsed_ms, len(ranked),
        )
        return ranked


def rerank_via_adapter(
    question: str,
    candidates: list[dict],
    model: str,
    *,
    api_base: str,
    api_key: str,
    extra_headers: dict | None = None,
    top_k: int = 8,
    stats_hook=None,
) -> tuple[list[dict], dict]:
    """Entry point compatible with pageindex_service._rerank_candidates_via_native_api."""
    docs = []
    for c in candidates:
        parts = [
            f"document: {c.get('document_label') or c.get('document_id') or 'unknown'}",
            f"title: {c.get('title') or 'untitled'}",
            f"pages: {c.get('page_start')}-{c.get('page_end')}",
        ]
        docs.append("\n".join(parts))
    adapter = GenericRerankAdapter(
        base_url=api_base,
        api_key=api_key,
        model=model,
        extra_headers=extra_headers,
    )
    try:
        results = adapter.rerank(query=question, documents=docs, top_n=top_k)
    except Exception as exc:
        if stats_hook:
            stats_hook({"ok": False, "error": str(exc)[:200]})
        raise
    ranked: list[dict] = []
    seen: set[int] = set()
    for item in results:
        idx = item["index"]
        if idx < 0 or idx >= len(candidates) or idx in seen:
            continue
        seen.add(idx)
        rc = dict(candidates[idx])
        rc["rerank_score"] = item["score"]
        rc["rerank_reason"] = None
        ranked.append(rc)
        if len(ranked) >= top_k:
            break
    if stats_hook:
        stats_hook({"ok": True, "results": len(results)})
    if not ranked:
        return candidates[:top_k], {"applied": False, "mode": "fallback_original_order"}
    return ranked, {"applied": True, "mode": "generic_rerank"}
