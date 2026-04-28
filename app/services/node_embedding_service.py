from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib import error, request

from app.core.config import get_settings
from app.services.provider_service import resolve_embedding_config
from app.services.storage_service import BaseArtifactStorage, get_storage_backend


NODE_EMBEDDING_ARTIFACT_SCHEMA_VERSION = "node_embedding_artifact_bundle_v1"
NODE_EMBEDDING_TEXT_SCHEMA_VERSION = "node_embedding_text_v4"
NODE_EMBEDDING_SECTION_TEXT_MAX_CHARS = 8_192
NODE_EMBEDDING_DENSE_SOURCE_SPARSE = "sparse"
NODE_EMBEDDING_DENSE_SOURCE_ARTIFACT_EXACT = "artifact_exact_scan"
NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW = "es_shadow"
DEFAULT_NODE_ES_INDEX_PREFIX = "pageindex-node-embeddings"
DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_BATCH_SIZE = 10
DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MAX_RETRIES = 2
DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_RETRY_BASE_SECONDS = 0.25
NODE_EMBEDDING_ARTIFACT_STATUS_COMPLETE = "complete"
NODE_EMBEDDING_ARTIFACT_STATUS_PARTIAL = "partial"
NODE_EMBEDDING_ARTIFACT_STATUS_FAILED = "failed"
NODE_EMBEDDING_ARTIFACT_LAYOUT_SINGLE_FILE = "single_file"
NODE_EMBEDDING_ARTIFACT_SHARD_RECOMMENDED_NODE_COUNT = 1000
_EMBEDDING_RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class NodeEmbeddingClient(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        ...


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(score, 1.0))


def _embedding_error_reason(exc: Exception) -> str:
    if isinstance(exc, error.HTTPError):
        code = getattr(exc, "code", None)
        return f"embedding_provider_http_error:{code}" if code is not None else "embedding_provider_http_error"
    if isinstance(exc, TimeoutError):
        return "embedding_provider_timeout"
    if isinstance(exc, error.URLError):
        return f"embedding_provider_url_error:{type(getattr(exc, 'reason', None)).__name__}"
    return f"embedding_provider_error:{type(exc).__name__}"


def _normalized_embedding_build_mode(value: Any) -> str:
    normalized = str(value or "disabled").strip().lower().replace("-", "_")
    if normalized in {"1", "true", "yes", "on", "enable", "enabled", "build"}:
        return "enabled"
    if normalized in {"dryrun", "dry_run", "dry"}:
        return "dry_run"
    return "disabled"


def _normalize_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _normalize_nonnegative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _normalize_nonnegative_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _env_positive_int(names: Sequence[str], default: int) -> int:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return _normalize_positive_int(value, default)
    return default


def _env_nonnegative_int(names: Sequence[str], default: int) -> int:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return _normalize_nonnegative_int(value, default)
    return default


def _env_nonnegative_float(names: Sequence[str], default: float) -> float:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return _normalize_nonnegative_float(value, default)
    return default


def _embedding_batch_size(
    embedding_config: Mapping[str, Any] | None = None,
    settings_obj: Any | None = None,
    client: Any | None = None,
) -> int:
    for key in ("batch_size", "max_batch_size", "embedding_batch_size"):
        if embedding_config and embedding_config.get(key) not in (None, ""):
            return _normalize_positive_int(
                embedding_config.get(key),
                DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_BATCH_SIZE,
            )
    for attr in ("system_embedding_batch_size", "node_embedding_batch_size", "embedding_batch_size"):
        if settings_obj is not None and getattr(settings_obj, attr, None) not in (None, ""):
            return _normalize_positive_int(
                getattr(settings_obj, attr),
                DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_BATCH_SIZE,
            )
    if client is not None and getattr(client, "max_batch_size", None) not in (None, ""):
        return _normalize_positive_int(
            getattr(client, "max_batch_size"),
            DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_BATCH_SIZE,
        )
    return _env_positive_int(
        (
            "SYSTEM_EMBEDDING_BATCH_SIZE",
            "NODE_EMBEDDING_BATCH_SIZE",
            "OPENAI_COMPATIBLE_EMBEDDING_BATCH_SIZE",
        ),
        DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_BATCH_SIZE,
    )


def _embedding_timeout_seconds(embedding_config: Mapping[str, Any] | None = None) -> int:
    for key in ("timeout_seconds", "request_timeout_seconds", "embedding_timeout_seconds"):
        if embedding_config and embedding_config.get(key) not in (None, ""):
            return _normalize_positive_int(embedding_config.get(key), 30)
    return _env_positive_int(
        (
            "SYSTEM_EMBEDDING_TIMEOUT_SECONDS",
            "NODE_EMBEDDING_TIMEOUT_SECONDS",
            "OPENAI_COMPATIBLE_EMBEDDING_TIMEOUT_SECONDS",
        ),
        30,
    )


def _embedding_max_retries(embedding_config: Mapping[str, Any] | None = None) -> int:
    for key in ("max_retries", "embedding_max_retries", "retry_count"):
        if embedding_config and embedding_config.get(key) not in (None, ""):
            return _normalize_nonnegative_int(
                embedding_config.get(key),
                DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MAX_RETRIES,
            )
    return _env_nonnegative_int(
        (
            "SYSTEM_EMBEDDING_MAX_RETRIES",
            "NODE_EMBEDDING_MAX_RETRIES",
            "OPENAI_COMPATIBLE_EMBEDDING_MAX_RETRIES",
        ),
        DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MAX_RETRIES,
    )


def _embedding_retry_base_seconds(embedding_config: Mapping[str, Any] | None = None) -> float:
    for key in ("retry_base_seconds", "embedding_retry_base_seconds"):
        if embedding_config and embedding_config.get(key) not in (None, ""):
            return _normalize_nonnegative_float(
                embedding_config.get(key),
                DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_RETRY_BASE_SECONDS,
            )
    return _env_nonnegative_float(
        (
            "SYSTEM_EMBEDDING_RETRY_BASE_SECONDS",
            "NODE_EMBEDDING_RETRY_BASE_SECONDS",
            "OPENAI_COMPATIBLE_EMBEDDING_RETRY_BASE_SECONDS",
        ),
        DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_RETRY_BASE_SECONDS,
    )


def embedding_runtime_options(
    embedding_config: Mapping[str, Any] | None = None,
    settings_obj: Any | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    return {
        "batch_size": _embedding_batch_size(embedding_config, settings_obj, client),
        "timeout_seconds": _embedding_timeout_seconds(embedding_config),
        "max_retries": _embedding_max_retries(embedding_config),
        "retry_base_seconds": _embedding_retry_base_seconds(embedding_config),
    }


def _sanitize_error_message(value: Any, max_len: int = 200) -> str:
    text = str(value or "").replace("\n", " ").strip()
    text = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ***", text)
    text = re.sub(r"sk-[A-Za-z0-9._-]+", "sk-***", text)
    return text[:max_len]


def _error_summary(exc: BaseException) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "error_type": type(exc).__name__,
        "message": _sanitize_error_message(exc),
    }
    status_code = getattr(exc, "code", None)
    if status_code is not None:
        summary["status_code"] = status_code
    reason = getattr(exc, "reason", None)
    if reason:
        summary["reason"] = _sanitize_error_message(reason)
    return summary


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _storage_prefix(prefix: str) -> str:
    cleaned = str(prefix or "").strip().strip("/")
    return f"{cleaned}/" if cleaned else ""


def _safe_path_part(value: Any, fallback: str) -> str:
    text = _normalize_text(value) or fallback
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)[:160] or fallback


def _manual_key(manual: Mapping[str, Any], node: Mapping[str, Any] | None = None) -> str:
    explicit = _normalize_text(manual.get("manual_key"))
    if explicit:
        return explicit
    document_id = _normalize_text(manual.get("document_id") or (node or {}).get("document_id")) or "unknown"
    version_id = _normalize_text(manual.get("version_id") or (node or {}).get("version_id")) or "unknown"
    return f"{document_id}:{version_id}"


def _page_span(node: Mapping[str, Any]) -> str | None:
    start = node.get("page_start")
    end = node.get("page_end")
    if start is None and end is None:
        return None
    if start is not None and end is not None:
        return f"{start}-{end}"
    return str(start if start is not None else end)


def _stringify_optional_tokens(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, Mapping):
        text = " ".join(str(item) for pair in value.items() for item in pair if _normalize_text(item))
        return _normalize_text(text)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        text = " ".join(str(item) for item in value if _normalize_text(item))
        return _normalize_text(text)
    return _normalize_text(value)


def _embedding_text_field(label: str, value: Any) -> str | None:
    text = _normalize_text(value)
    if text is None:
        return None
    if label == "section_text" and len(text) > NODE_EMBEDDING_SECTION_TEXT_MAX_CHARS:
        return text[:NODE_EMBEDDING_SECTION_TEXT_MAX_CHARS].rstrip() + "\n...[section_text truncated for embedding]"
    return text


def build_node_embedding_text(manual: Mapping[str, Any], node: Mapping[str, Any]) -> str:
    """Build stable node embedding text without requiring route_summary."""

    parts: list[tuple[str, Any]] = [
        ("title", node.get("title")),
        ("breadcrumb", node.get("breadcrumb")),
        ("page_span", _page_span(node)),
        ("depth", node.get("depth")),
        ("document_label", manual.get("document_label") or node.get("document_label")),
        ("version_label", manual.get("version_label") or node.get("version_label")),
        ("display_name", manual.get("display_name") or node.get("display_name")),
        ("source_filename", manual.get("source_filename") or node.get("source_filename")),
        ("aliases", _stringify_optional_tokens(node.get("aliases"))),
        ("keywords", _stringify_optional_tokens(node.get("keywords"))),
        ("manual_profile", node.get("manual_profile_text")),
        ("contrastive_summary", node.get("contrastive_summary")),
        ("route_summary", node.get("route_summary")),
        ("section_text", node.get("section_text")),
    ]
    lines = [f"{label}: {text}" for label, value in parts if (text := _embedding_text_field(label, value))]
    return "\n".join(lines)


def embedding_spec_id_for_config(
    embedding_config: Mapping[str, Any],
    *,
    text_schema_version: str = NODE_EMBEDDING_TEXT_SCHEMA_VERSION,
) -> str:
    explicit = _normalize_text(embedding_config.get("embedding_spec_id"))
    if explicit:
        return explicit
    spec = {
        "provider_source": _normalize_text(embedding_config.get("provider_source")),
        "provider_type": _normalize_text(embedding_config.get("provider_type")),
        "model": _normalize_text(embedding_config.get("model")),
        "dimensions": embedding_config.get("dimensions") or "provider_default",
        "text_schema_version": text_schema_version,
    }
    return f"node-emb-{_json_hash(spec)[:16]}"


def es_index_name_for_embedding_bundle(
    *,
    routing_index_version: str | None,
    embedding_spec_id: str,
    index_prefix: str | None = None,
) -> str:
    prefix = _safe_path_part(index_prefix or DEFAULT_NODE_ES_INDEX_PREFIX, DEFAULT_NODE_ES_INDEX_PREFIX).lower()
    routing_version = _safe_path_part(routing_index_version or "v1", "v1").lower()
    spec = _safe_path_part(embedding_spec_id, "node-emb").lower()
    return f"{prefix}-{routing_version}-{spec}"


def _artifact_object_path(
    *,
    document_id: str,
    version_id: str,
    routing_index_version: str,
    embedding_spec_id: str,
) -> str:
    return (
        f"documents/{_safe_path_part(document_id, 'unknown')}/"
        f"versions/{_safe_path_part(version_id, 'unknown')}/"
        f"routing_embeddings/{_safe_path_part(routing_index_version, 'v1')}/"
        f"{_safe_path_part(embedding_spec_id, 'node-emb')}/bundle.json"
    )


@dataclass
class NodeEmbeddingArtifactResult:
    available: bool
    bundle: dict[str, Any] | None = None
    uri: str | None = None
    object_path: str | None = None
    embedding_spec_id: str | None = None
    built: bool = False
    written: bool = False
    fallback_reason: str | None = None

    def summary(self) -> dict[str, Any]:
        manifest = (self.bundle or {}).get("manifest") if isinstance(self.bundle, Mapping) else {}
        bundle_key = (self.bundle or {}).get("bundle_key") if isinstance(self.bundle, Mapping) else {}
        return {
            "available": self.available,
            "uri": self.uri,
            "object_path": self.object_path,
            "embedding_spec_id": self.embedding_spec_id,
            "document_id": (bundle_key or {}).get("document_id"),
            "version_id": (bundle_key or {}).get("version_id"),
            "routing_index_version": (bundle_key or {}).get("routing_index_version"),
            "artifact_status": (manifest or {}).get("status"),
            "artifact_complete": (manifest or {}).get("complete"),
            "artifact_layout": (manifest or {}).get("artifact_layout"),
            "sharded": (manifest or {}).get("sharded"),
            "node_count": (manifest or {}).get("node_count"),
            "embedded_node_count": (manifest or {}).get("embedded_node_count"),
            "failed_node_count": (manifest or {}).get("failed_node_count"),
            "batch_size": (manifest or {}).get("batch_size"),
            "batch_count": (manifest or {}).get("batch_count"),
            "failed_batch_count": len((manifest or {}).get("failed_batches") or []),
            "failed_batches": list((manifest or {}).get("failed_batches") or []),
            "built": self.built,
            "written": self.written,
            "fallback_reason": self.fallback_reason,
        }


def _bundle_nodes(bundle: Mapping[str, Any]) -> list[Any]:
    nodes = bundle.get("nodes")
    return list(nodes) if isinstance(nodes, list) else []


def _complete_embedding_node_count(bundle: Mapping[str, Any]) -> int:
    count = 0
    for node in _bundle_nodes(bundle):
        if not isinstance(node, Mapping):
            continue
        embedding = node.get("embedding")
        if isinstance(embedding, Sequence) and not isinstance(embedding, (str, bytes, bytearray)) and embedding:
            count += 1
    return count


def _is_complete_embedding_bundle(bundle: Mapping[str, Any]) -> bool:
    if bundle.get("schema_version") != NODE_EMBEDDING_ARTIFACT_SCHEMA_VERSION:
        return False
    manifest = bundle.get("manifest") if isinstance(bundle.get("manifest"), Mapping) else {}
    status = manifest.get("status")
    if status not in {None, NODE_EMBEDDING_ARTIFACT_STATUS_COMPLETE}:
        return False
    nodes = _bundle_nodes(bundle)
    node_count = int(manifest.get("node_count") or len(nodes))
    return bool(nodes) and len(nodes) == node_count and _complete_embedding_node_count(bundle) == node_count


def _normalize_loaded_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(bundle)
    manifest = dict(normalized.get("manifest") or {})
    nodes = _bundle_nodes(normalized)
    embedded_count = _complete_embedding_node_count(normalized)
    node_count = int(manifest.get("node_count") or len(nodes))
    if manifest.get("status") is None:
        manifest.update(
            {
                "status": NODE_EMBEDDING_ARTIFACT_STATUS_COMPLETE,
                "complete": True,
                "embedded_node_count": embedded_count,
                "failed_node_count": max(0, node_count - embedded_count),
                "batch_size": manifest.get("batch_size"),
                "batch_count": manifest.get("batch_count"),
                "failed_batches": [],
                "artifact_layout": NODE_EMBEDDING_ARTIFACT_LAYOUT_SINGLE_FILE,
                "sharded": False,
                "shard_count": 0,
                "legacy_bundle": True,
            }
        )
    normalized["manifest"] = manifest
    return normalized


def _batch_failure_payload(
    *,
    batch_index: int,
    batch_start: int,
    batch_node_payloads: Sequence[Mapping[str, Any]],
    exc: BaseException,
    attempt_count: int | None = None,
) -> dict[str, Any]:
    payload = {
        "batch_index": batch_index,
        "batch_start": batch_start,
        "batch_size": len(batch_node_payloads),
        "node_ids": [
            str(node.get("node_id"))
            for node in batch_node_payloads
            if _normalize_text(node.get("node_id"))
        ],
        "node_keys": [
            str(node.get("node_key"))
            for node in batch_node_payloads
            if _normalize_text(node.get("node_key"))
        ],
        **_error_summary(exc),
    }
    if attempt_count is not None:
        payload["attempt_count"] = attempt_count
    return payload


@dataclass
class PreparedDenseSearch:
    embedding_config: dict[str, Any]
    artifact_results: list[NodeEmbeddingArtifactResult]
    query_vector: list[float]
    query_dimensions: int


@dataclass
class NodeDenseSearchResult:
    dense_scores: dict[str, float]
    dense_source: str
    enabled: bool
    fallback_reason: str | None = None
    requested_dense_source: str | None = None
    query_embedding_dimensions: int | None = None
    artifacts: list[dict[str, Any]] | None = None
    es: dict[str, Any] | None = None

    def metadata(self) -> dict[str, Any]:
        return {
            "dense_source": self.dense_source,
            "requested_dense_source": self.requested_dense_source or self.dense_source,
            "fallback_reason": self.fallback_reason,
            "query_embedding_dimensions": self.query_embedding_dimensions,
            "artifact_count": len(self.artifacts or []),
            "artifacts": list(self.artifacts or []),
            "es": dict(self.es or {}),
        }


class OpenAICompatibleEmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        provider_type: str | None = None,
        dimensions: int | None = None,
        timeout_seconds: int = 30,
        max_batch_size: int = DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_BATCH_SIZE,
        max_retries: int = DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_MAX_RETRIES,
        retry_base_seconds: float = DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_RETRY_BASE_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.provider_type = provider_type
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds
        self.max_batch_size = max(1, int(max_batch_size or DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_BATCH_SIZE))
        self.max_retries = max(0, int(max_retries or 0))
        self.retry_base_seconds = max(0.0, float(retry_base_seconds or 0.0))

    @classmethod
    def from_embedding_config(cls, embedding_config: Mapping[str, Any]) -> "OpenAICompatibleEmbeddingClient" | None:
        base_url = _normalize_text(embedding_config.get("base_url"))
        api_key = _normalize_text(embedding_config.get("api_key"))
        model = _normalize_text(embedding_config.get("model"))
        if not base_url or not api_key or not model:
            return None
        dimensions = embedding_config.get("dimensions")
        try:
            resolved_dimensions = int(dimensions) if dimensions is not None else None
        except (TypeError, ValueError):
            resolved_dimensions = None
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            provider_type=_normalize_text(embedding_config.get("provider_type")),
            dimensions=resolved_dimensions,
            timeout_seconds=_embedding_timeout_seconds(embedding_config),
            max_batch_size=_embedding_batch_size(embedding_config),
            max_retries=_embedding_max_retries(embedding_config),
            retry_base_seconds=_embedding_retry_base_seconds(embedding_config),
        )

    def _endpoint(self) -> str:
        if self.base_url.endswith("/embeddings"):
            return self.base_url
        return f"{self.base_url}/embeddings"

    def _request_model(self) -> str:
        if self.provider_type == "openai_compatible" and self.model.startswith("openai/"):
            return self.model.removeprefix("openai/")
        return self.model

    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        payload: dict[str, Any] = {
            "model": self._request_model(),
            "input": list(texts),
        }
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions
        req = request.Request(
            self._endpoint(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        max_attempts = self.max_retries + 1
        for attempt in range(max_attempts):
            try:
                with request.urlopen(req, timeout=self.timeout_seconds) as response:
                    decoded = json.loads(response.read().decode("utf-8"))
                break
            except error.HTTPError as exc:
                retryable = getattr(exc, "code", None) in _EMBEDDING_RETRYABLE_HTTP_STATUS_CODES
                if not retryable or attempt >= self.max_retries:
                    raise
                time.sleep(self.retry_base_seconds * (2**attempt))
            except (error.URLError, TimeoutError) as exc:
                if attempt >= self.max_retries:
                    raise
                time.sleep(self.retry_base_seconds * (2**attempt))
        else:  # pragma: no cover - loop exits by break or raise.
            raise RuntimeError("embedding_retry_exhausted")
        data = decoded.get("data") if isinstance(decoded, Mapping) else None
        if not isinstance(data, list):
            raise RuntimeError("embedding_response_missing_data")
        vectors: list[list[float]] = []
        for item in data:
            embedding = item.get("embedding") if isinstance(item, Mapping) else None
            if not isinstance(embedding, list):
                raise RuntimeError("embedding_response_missing_embedding")
            vectors.append([float(value) for value in embedding])
        if len(vectors) != len(texts):
            raise RuntimeError("embedding_response_count_mismatch")
        return vectors

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        text_list = list(texts)
        if not text_list:
            return []
        if len(text_list) <= self.max_batch_size:
            return self._embed_batch(text_list)

        vectors: list[list[float]] = []
        for start in range(0, len(text_list), self.max_batch_size):
            vectors.extend(self._embed_batch(text_list[start : start + self.max_batch_size]))
        if len(vectors) != len(text_list):
            raise RuntimeError("embedding_response_count_mismatch")
        return vectors


class NodeEmbeddingArtifactStore:
    def __init__(
        self,
        *,
        storage: BaseArtifactStorage | None = None,
        settings_obj: Any | None = None,
        embedding_client: NodeEmbeddingClient | None = None,
    ) -> None:
        self.storage = storage or get_storage_backend()
        self.settings = settings_obj or get_settings()
        self.embedding_client = embedding_client

    def bundle_uri(
        self,
        *,
        tenant_id: str,
        document_id: str,
        version_id: str,
        routing_index_version: str,
        embedding_spec_id: str,
    ) -> str:
        object_path = _artifact_object_path(
            document_id=document_id,
            version_id=version_id,
            routing_index_version=routing_index_version,
            embedding_spec_id=embedding_spec_id,
        )
        if getattr(self.settings, "storage_backend", "local") == "minio":
            prefix = _storage_prefix(getattr(self.settings, "minio_prefix_path", ""))
            return f"minio://{self.settings.minio_bucket}/{prefix}tenants/{tenant_id}/{object_path}"
        return str(self.settings.data_dir / "tenants" / tenant_id / object_path)

    def _client_for_config(self, embedding_config: Mapping[str, Any]) -> NodeEmbeddingClient | None:
        if self.embedding_client is not None:
            return self.embedding_client
        return OpenAICompatibleEmbeddingClient.from_embedding_config(embedding_config)

    def _load_existing(self, uri: str) -> dict[str, Any] | None:
        try:
            if self.storage.exists(uri):
                payload = self.storage.read_json(uri)
                if isinstance(payload, Mapping) and _is_complete_embedding_bundle(payload):
                    return _normalize_loaded_bundle(payload)
        except Exception:
            return None
        return None

    def _status_bundle(
        self,
        *,
        bundle_key: Mapping[str, Any],
        embedding_config: Mapping[str, Any],
        node_payloads: Sequence[Mapping[str, Any]],
        status: str,
        batch_size: int,
        batch_count: int,
        embedded_node_count: int,
        failed_batches: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        node_count = len(node_payloads)
        failed_node_count = max(0, node_count - embedded_node_count)
        manifest_base = {
            "provider_source": _normalize_text(embedding_config.get("provider_source")),
            "provider_type": _normalize_text(embedding_config.get("provider_type")),
            "model": _normalize_text(embedding_config.get("model")),
            "dimensions": embedding_config.get("dimensions") or "provider_default",
            "text_schema_version": NODE_EMBEDDING_TEXT_SCHEMA_VERSION,
            "node_count": node_count,
            "embedded_node_count": embedded_node_count,
            "failed_node_count": failed_node_count,
            "status": status,
            "complete": status == NODE_EMBEDDING_ARTIFACT_STATUS_COMPLETE,
            "supported_statuses": [
                NODE_EMBEDDING_ARTIFACT_STATUS_COMPLETE,
                NODE_EMBEDDING_ARTIFACT_STATUS_PARTIAL,
                NODE_EMBEDDING_ARTIFACT_STATUS_FAILED,
            ],
            "batch_size": batch_size,
            "batch_count": batch_count,
            "failed_batches": [dict(batch) for batch in failed_batches],
            "artifact_layout": NODE_EMBEDDING_ARTIFACT_LAYOUT_SINGLE_FILE,
            "sharded": False,
            "shard_count": 0,
            "shard_recommended_above_node_count": NODE_EMBEDDING_ARTIFACT_SHARD_RECOMMENDED_NODE_COUNT,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "text_checksum": _json_hash([{"node_key": node["node_key"], "text_hash": node["text_hash"]} for node in node_payloads]),
            "node_checksum": _json_hash([{"node_key": node["node_key"], "node_id": node["node_id"]} for node in node_payloads]),
        }
        manifest = {
            **manifest_base,
            "manifest_hash": _json_hash({"bundle_key": dict(bundle_key), "manifest": manifest_base}),
        }
        bundle = {
            "schema_version": NODE_EMBEDDING_ARTIFACT_SCHEMA_VERSION,
            "bundle_key": dict(bundle_key),
            "manifest": manifest,
            "nodes": [],
        }
        bundle["bundle_hash"] = _json_hash(bundle)
        return bundle

    def get_or_build(
        self,
        *,
        manual: Mapping[str, Any],
        nodes: Sequence[Mapping[str, Any]],
        embedding_config: Mapping[str, Any],
        force_rebuild: bool = False,
    ) -> NodeEmbeddingArtifactResult:
        document_id = _normalize_text(manual.get("document_id")) or "unknown"
        version_id = _normalize_text(manual.get("version_id")) or "unknown"
        tenant_id = _normalize_text(manual.get("tenant_id")) or "shadow"
        routing_index_version = _normalize_text(manual.get("routing_index_version")) or "v1"
        embedding_spec_id = embedding_spec_id_for_config(embedding_config)
        object_path = _artifact_object_path(
            document_id=document_id,
            version_id=version_id,
            routing_index_version=routing_index_version,
            embedding_spec_id=embedding_spec_id,
        )
        uri = self.bundle_uri(
            tenant_id=tenant_id,
            document_id=document_id,
            version_id=version_id,
            routing_index_version=routing_index_version,
            embedding_spec_id=embedding_spec_id,
        )
        build_mode = _normalized_embedding_build_mode(getattr(self.settings, "routing_embeddings_build_mode", "disabled"))

        if not force_rebuild:
            existing = self._load_existing(uri)
            if existing is not None:
                manifest = existing.get("manifest") if isinstance(existing.get("manifest"), Mapping) else {}
                if build_mode != "enabled" or not manifest.get("legacy_bundle"):
                    return NodeEmbeddingArtifactResult(
                        available=True,
                        bundle=existing,
                        uri=uri,
                        object_path=object_path,
                        embedding_spec_id=embedding_spec_id,
                    )

        node_list = [dict(node) for node in nodes if isinstance(node, Mapping)]
        if not node_list:
            return NodeEmbeddingArtifactResult(
                available=False,
                uri=uri,
                object_path=object_path,
                embedding_spec_id=embedding_spec_id,
                fallback_reason="node_corpus_empty",
            )

        if build_mode == "disabled":
            return NodeEmbeddingArtifactResult(
                available=False,
                uri=uri,
                object_path=object_path,
                embedding_spec_id=embedding_spec_id,
                fallback_reason="embedding_build_mode_disabled",
            )
        if not embedding_config.get("enabled"):
            fallback_reason = _normalize_text(embedding_config.get("fallback_reason")) or "embedding_unavailable"
            return NodeEmbeddingArtifactResult(
                available=False,
                uri=uri,
                object_path=object_path,
                embedding_spec_id=embedding_spec_id,
                fallback_reason=f"embedding_unavailable:{fallback_reason}",
            )

        client = self._client_for_config(embedding_config)
        if client is None:
            return NodeEmbeddingArtifactResult(
                available=False,
                uri=uri,
                object_path=object_path,
                embedding_spec_id=embedding_spec_id,
                fallback_reason="embedding_client_unavailable",
            )

        node_payloads: list[dict[str, Any]] = []
        texts: list[str] = []
        for index, node in enumerate(node_list):
            node_id = _normalize_text(node.get("node_id"))
            if not node_id:
                continue
            text = build_node_embedding_text(manual, node)
            if not text:
                continue
            manual_key = _manual_key(manual, node)
            node_key = _normalize_text(node.get("node_key")) or f"{manual_key}:{node_id}"
            node_payloads.append(
                {
                    "node_id": node_id,
                    "node_key": node_key,
                    "document_id": _normalize_text(node.get("document_id")) or document_id,
                    "version_id": _normalize_text(node.get("version_id")) or version_id,
                    "text": text,
                    "title": _normalize_text(node.get("title")),
                    "breadcrumb": _normalize_text(node.get("breadcrumb")),
                    "summary": _normalize_text(node.get("route_summary")),
                    "section_text": _normalize_text(node.get("section_text")),
                    "page_start": node.get("page_start"),
                    "page_end": node.get("page_end"),
                    "text_hash": _json_hash({"text_schema_version": NODE_EMBEDDING_TEXT_SCHEMA_VERSION, "text": text}),
                    "original_index": node.get("original_index", index),
                }
            )
            texts.append(text)

        if not node_payloads:
            return NodeEmbeddingArtifactResult(
                available=False,
                uri=uri,
                object_path=object_path,
                embedding_spec_id=embedding_spec_id,
                fallback_reason="node_embedding_text_empty",
            )

        batch_size = _embedding_batch_size(embedding_config, self.settings, client)
        batch_count = math.ceil(len(texts) / batch_size)
        vectors: list[list[float]] = []
        failed_batches: list[dict[str, Any]] = []
        for batch_index, batch_start in enumerate(range(0, len(texts), batch_size)):
            batch_texts = texts[batch_start : batch_start + batch_size]
            batch_node_payloads = node_payloads[batch_start : batch_start + batch_size]
            try:
                batch_vectors = client.embed(batch_texts)
            except Exception as exc:
                failed_batches.append(
                    _batch_failure_payload(
                        batch_index=batch_index,
                        batch_start=batch_start,
                        batch_node_payloads=batch_node_payloads,
                        exc=exc,
                    )
                )
                failure_bundle = self._status_bundle(
                    bundle_key={
                        "document_id": document_id,
                        "version_id": version_id,
                        "routing_index_version": routing_index_version,
                        "embedding_spec_id": embedding_spec_id,
                    },
                    embedding_config=embedding_config,
                    node_payloads=node_payloads,
                    status=(
                        NODE_EMBEDDING_ARTIFACT_STATUS_PARTIAL
                        if vectors
                        else NODE_EMBEDDING_ARTIFACT_STATUS_FAILED
                    ),
                    batch_size=batch_size,
                    batch_count=batch_count,
                    embedded_node_count=len(vectors),
                    failed_batches=failed_batches,
                )
                return NodeEmbeddingArtifactResult(
                    available=False,
                    bundle=failure_bundle,
                    uri=uri,
                    object_path=object_path,
                    embedding_spec_id=embedding_spec_id,
                    fallback_reason=_embedding_error_reason(exc),
                )
            if len(batch_vectors) != len(batch_texts):
                exc = RuntimeError("embedding_response_count_mismatch")
                failed_batches.append(
                    _batch_failure_payload(
                        batch_index=batch_index,
                        batch_start=batch_start,
                        batch_node_payloads=batch_node_payloads,
                        exc=exc,
                    )
                )
                failure_bundle = self._status_bundle(
                    bundle_key={
                        "document_id": document_id,
                        "version_id": version_id,
                        "routing_index_version": routing_index_version,
                        "embedding_spec_id": embedding_spec_id,
                    },
                    embedding_config=embedding_config,
                    node_payloads=node_payloads,
                    status=(
                        NODE_EMBEDDING_ARTIFACT_STATUS_PARTIAL
                        if vectors
                        else NODE_EMBEDDING_ARTIFACT_STATUS_FAILED
                    ),
                    batch_size=batch_size,
                    batch_count=batch_count,
                    embedded_node_count=len(vectors),
                    failed_batches=failed_batches,
                )
                return NodeEmbeddingArtifactResult(
                    available=False,
                    bundle=failure_bundle,
                    uri=uri,
                    object_path=object_path,
                    embedding_spec_id=embedding_spec_id,
                    fallback_reason="embedding_vector_count_mismatch",
                )
            vectors.extend(batch_vectors)

        if failed_batches:
            return NodeEmbeddingArtifactResult(
                available=False,
                uri=uri,
                object_path=object_path,
                embedding_spec_id=embedding_spec_id,
                fallback_reason="embedding_batch_failed",
            )
        if len(vectors) != len(node_payloads):
            return NodeEmbeddingArtifactResult(
                available=False,
                uri=uri,
                object_path=object_path,
                embedding_spec_id=embedding_spec_id,
                fallback_reason="embedding_vector_count_mismatch",
            )

        dimensions = len(vectors[0]) if vectors else 0
        if dimensions <= 0 or any(len(vector) != dimensions for vector in vectors):
            return NodeEmbeddingArtifactResult(
                available=False,
                uri=uri,
                object_path=object_path,
                embedding_spec_id=embedding_spec_id,
                fallback_reason="embedding_dimension_mismatch",
            )

        for node_payload, vector in zip(node_payloads, vectors, strict=True):
            normalized_vector = [float(value) for value in vector]
            node_payload["embedding"] = normalized_vector
            node_payload["embedding_hash"] = _json_hash(normalized_vector)

        bundle_key = {
            "document_id": document_id,
            "version_id": version_id,
            "routing_index_version": routing_index_version,
            "embedding_spec_id": embedding_spec_id,
        }
        manifest_base = {
            "provider_source": _normalize_text(embedding_config.get("provider_source")),
            "provider_type": _normalize_text(embedding_config.get("provider_type")),
            "model": _normalize_text(embedding_config.get("model")),
            "dimensions": dimensions,
            "text_schema_version": NODE_EMBEDDING_TEXT_SCHEMA_VERSION,
            "node_count": len(node_payloads),
            "embedded_node_count": len(node_payloads),
            "failed_node_count": 0,
            "status": NODE_EMBEDDING_ARTIFACT_STATUS_COMPLETE,
            "complete": True,
            "batch_size": batch_size,
            "batch_count": batch_count,
            "failed_batches": [],
            "artifact_layout": NODE_EMBEDDING_ARTIFACT_LAYOUT_SINGLE_FILE,
            "sharded": False,
            "shard_count": 0,
            "shard_recommended_above_node_count": NODE_EMBEDDING_ARTIFACT_SHARD_RECOMMENDED_NODE_COUNT,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "text_checksum": _json_hash([{"node_key": node["node_key"], "text_hash": node["text_hash"]} for node in node_payloads]),
            "section_text_checksum": _json_hash([
                {
                    "node_key": node["node_key"],
                    "section_text": _normalize_text(node.get("section_text")) or "",
                }
                for node in node_payloads
            ]),
            "embedding_checksum": _json_hash([{"node_key": node["node_key"], "embedding_hash": node["embedding_hash"]} for node in node_payloads]),
            "node_checksum": _json_hash([{"node_key": node["node_key"], "node_id": node["node_id"]} for node in node_payloads]),
        }
        manifest = {
            **manifest_base,
            "manifest_hash": _json_hash({"bundle_key": bundle_key, "manifest": manifest_base}),
        }
        bundle = {
            "schema_version": NODE_EMBEDDING_ARTIFACT_SCHEMA_VERSION,
            "bundle_key": bundle_key,
            "manifest": manifest,
            "nodes": node_payloads,
        }
        bundle["bundle_hash"] = _json_hash(bundle)

        written = False
        if build_mode == "enabled":
            try:
                uri = self.storage.write_json(bundle, tenant_id=tenant_id, object_path=object_path)
                written = True
            except Exception as exc:
                return NodeEmbeddingArtifactResult(
                    available=False,
                    bundle=bundle,
                    uri=uri,
                    object_path=object_path,
                    embedding_spec_id=embedding_spec_id,
                    built=True,
                    fallback_reason=f"embedding_artifact_write_error:{type(exc).__name__}",
                )

        return NodeEmbeddingArtifactResult(
            available=True,
            bundle=bundle,
            uri=uri,
            object_path=object_path,
            embedding_spec_id=embedding_spec_id,
            built=True,
            written=written,
        )


class NodeDenseSearchBackend:
    dense_source = NODE_EMBEDDING_DENSE_SOURCE_SPARSE

    def search(
        self,
        *,
        query: str,
        node_corpora: Sequence[Mapping[str, Any]],
        embedding_mode: str | None = None,
        provider_config: Mapping[str, Any] | None = None,
        embedding_config: Mapping[str, Any] | None = None,
        settings_obj: Any | None = None,
    ) -> NodeDenseSearchResult:
        raise NotImplementedError


class ExactScanNodeDenseSearchBackend(NodeDenseSearchBackend):
    dense_source = NODE_EMBEDDING_DENSE_SOURCE_ARTIFACT_EXACT

    def __init__(
        self,
        *,
        artifact_store: NodeEmbeddingArtifactStore | None = None,
        embedding_client: NodeEmbeddingClient | None = None,
    ) -> None:
        self.artifact_store = artifact_store or NodeEmbeddingArtifactStore(embedding_client=embedding_client)
        self.embedding_client = embedding_client

    def _resolve_embedding_config(
        self,
        *,
        embedding_mode: str | None,
        provider_config: Mapping[str, Any] | None,
        embedding_config: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if embedding_config is not None:
            return dict(embedding_config)
        return dict(
            resolve_embedding_config(
                provider_config=dict(provider_config or {}),
                embedding_mode=embedding_mode,
            )
        )

    def _client_for_config(self, embedding_config: Mapping[str, Any]) -> NodeEmbeddingClient | None:
        if self.embedding_client is not None:
            return self.embedding_client
        if self.artifact_store.embedding_client is not None:
            return self.artifact_store.embedding_client
        return OpenAICompatibleEmbeddingClient.from_embedding_config(embedding_config)

    def _prepare(
        self,
        *,
        query: str,
        node_corpora: Sequence[Mapping[str, Any]],
        embedding_mode: str | None,
        provider_config: Mapping[str, Any] | None,
        embedding_config: Mapping[str, Any] | None,
    ) -> tuple[PreparedDenseSearch | None, NodeDenseSearchResult | None]:
        normalized_query = _normalize_text(query)
        if not normalized_query:
            return None, NodeDenseSearchResult(
                dense_scores={},
                dense_source=self.dense_source,
                requested_dense_source=self.dense_source,
                enabled=False,
                fallback_reason="query_empty",
            )
        resolved_config = self._resolve_embedding_config(
            embedding_mode=embedding_mode,
            provider_config=provider_config,
            embedding_config=embedding_config,
        )
        if not resolved_config.get("enabled"):
            fallback_reason = _normalize_text(resolved_config.get("fallback_reason")) or "embedding_unavailable"
            return None, NodeDenseSearchResult(
                dense_scores={},
                dense_source=self.dense_source,
                requested_dense_source=self.dense_source,
                enabled=False,
                fallback_reason=f"embedding_unavailable:{fallback_reason}",
            )

        artifact_results: list[NodeEmbeddingArtifactResult] = []
        for corpus in node_corpora:
            if not isinstance(corpus, Mapping):
                continue
            manual = corpus.get("manual") if isinstance(corpus.get("manual"), Mapping) else {}
            nodes = corpus.get("nodes") if isinstance(corpus.get("nodes"), Sequence) else []
            artifact_results.append(
                self.artifact_store.get_or_build(
                    manual=dict(manual),
                    nodes=[dict(node) for node in nodes if isinstance(node, Mapping)],
                    embedding_config=resolved_config,
                )
            )

        available_artifacts = [result for result in artifact_results if result.available and result.bundle]
        if not available_artifacts:
            reasons = [result.fallback_reason for result in artifact_results if result.fallback_reason]
            fallback_reason = reasons[0] if reasons else "embedding_artifact_unavailable"
            return None, NodeDenseSearchResult(
                dense_scores={},
                dense_source=self.dense_source,
                requested_dense_source=self.dense_source,
                enabled=False,
                fallback_reason=fallback_reason,
                artifacts=[result.summary() for result in artifact_results],
            )

        client = self._client_for_config(resolved_config)
        if client is None:
            return None, NodeDenseSearchResult(
                dense_scores={},
                dense_source=self.dense_source,
                requested_dense_source=self.dense_source,
                enabled=False,
                fallback_reason="embedding_client_unavailable",
                artifacts=[result.summary() for result in artifact_results],
            )
        try:
            query_vectors = client.embed([normalized_query])
        except Exception as exc:
            return None, NodeDenseSearchResult(
                dense_scores={},
                dense_source=self.dense_source,
                requested_dense_source=self.dense_source,
                enabled=False,
                fallback_reason=_embedding_error_reason(exc),
                artifacts=[result.summary() for result in artifact_results],
            )
        if not query_vectors or not query_vectors[0]:
            return None, NodeDenseSearchResult(
                dense_scores={},
                dense_source=self.dense_source,
                requested_dense_source=self.dense_source,
                enabled=False,
                fallback_reason="query_embedding_empty",
                artifacts=[result.summary() for result in artifact_results],
            )
        query_vector = [float(value) for value in query_vectors[0]]
        return PreparedDenseSearch(
            embedding_config=resolved_config,
            artifact_results=artifact_results,
            query_vector=query_vector,
            query_dimensions=len(query_vector),
        ), None

    @staticmethod
    def _cosine_score(query_vector: Sequence[float], node_vector: Sequence[float]) -> float | None:
        if len(query_vector) != len(node_vector) or not query_vector:
            return None
        dot = sum(float(left) * float(right) for left, right in zip(query_vector, node_vector, strict=True))
        query_norm = math.sqrt(sum(float(value) * float(value) for value in query_vector))
        node_norm = math.sqrt(sum(float(value) * float(value) for value in node_vector))
        if query_norm <= 0 or node_norm <= 0:
            return None
        cosine = dot / (query_norm * node_norm)
        return max(0.0, min((cosine + 1.0) / 2.0, 1.0))

    def _search_prepared(
        self,
        prepared: PreparedDenseSearch,
        *,
        requested_dense_source: str | None = None,
        es: dict[str, Any] | None = None,
    ) -> NodeDenseSearchResult:
        dense_scores: dict[str, float] = {}
        dimension_mismatch_count = 0
        for artifact_result in prepared.artifact_results:
            bundle = artifact_result.bundle if artifact_result.available else None
            if not isinstance(bundle, Mapping):
                continue
            for node in bundle.get("nodes") or []:
                if not isinstance(node, Mapping):
                    continue
                vector = node.get("embedding")
                if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes, bytearray)):
                    continue
                score = self._cosine_score(prepared.query_vector, [float(value) for value in vector])
                if score is None:
                    dimension_mismatch_count += 1
                    continue
                node_key = _normalize_text(node.get("node_key"))
                if node_key:
                    dense_scores[node_key] = round(score, 6)
        fallback_reason = None if dense_scores else "embedding_artifact_no_matching_vectors"
        es_metadata = dict(es or {})
        if dimension_mismatch_count:
            es_metadata["dimension_mismatch_count"] = dimension_mismatch_count
        return NodeDenseSearchResult(
            dense_scores=dense_scores,
            dense_source=self.dense_source,
            requested_dense_source=requested_dense_source or self.dense_source,
            enabled=bool(dense_scores),
            fallback_reason=fallback_reason,
            query_embedding_dimensions=prepared.query_dimensions,
            artifacts=[result.summary() for result in prepared.artifact_results],
            es=es_metadata,
        )

    def search(
        self,
        *,
        query: str,
        node_corpora: Sequence[Mapping[str, Any]],
        embedding_mode: str | None = None,
        provider_config: Mapping[str, Any] | None = None,
        embedding_config: Mapping[str, Any] | None = None,
        settings_obj: Any | None = None,
    ) -> NodeDenseSearchResult:
        prepared, fallback = self._prepare(
            query=query,
            node_corpora=node_corpora,
            embedding_mode=embedding_mode,
            provider_config=provider_config,
            embedding_config=embedding_config,
        )
        if fallback is not None:
            return fallback
        assert prepared is not None
        return self._search_prepared(prepared)


# ── ES Index Management ──────────────────────────────────────────────────────


def build_es_index_mapping(dimensions: int) -> dict:
    """Build ES index mapping for node embedding index.

    Fields:
    - tenant_id, workspace_id (optional/reserved), document_id, version_id,
      node_id, node_key, embedding_spec_id, routing_index_version: keyword filters
    - text: full-text content of the node embedding text
    - embedding: dense_vector (dims=dimensions, similarity=cosine)
    - synced_at: ISO date for sync tracking
    """
    text_field = {"type": "text", "analyzer": "pageindex_cjk_ngram", "search_analyzer": "standard"}
    return {
        "settings": {
            "index": {
                "max_ngram_diff": 3,
            },
            "analysis": {
                "filter": {
                    "pageindex_cjk_ngram_filter": {
                        "type": "ngram",
                        "min_gram": 2,
                        "max_gram": 4,
                    }
                },
                "analyzer": {
                    "pageindex_cjk_ngram": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "pageindex_cjk_ngram_filter"],
                    }
                },
            }
        },
        "mappings": {
            "properties": {
                "tenant_id": {"type": "keyword"},
                "workspace_id": {"type": "keyword"},  # reserved, not required
                "document_id": {"type": "keyword"},
                "version_id": {"type": "keyword"},
                "node_id": {"type": "keyword"},
                "node_key": {"type": "keyword"},
                "embedding_spec_id": {"type": "keyword"},
                "routing_index_version": {"type": "keyword"},
                "page_start": {"type": "integer"},
                "page_end": {"type": "integer"},
                "title": text_field,
                "breadcrumb": text_field,
                "summary": text_field,
                "section_text": text_field,
                "section_text_checksum": {"type": "keyword"},
                "text": text_field,
                "embedding": {
                    "type": "dense_vector",
                    "dims": dimensions,
                    "index": True,
                    "similarity": "cosine",
                },
                "synced_at": {"type": "date"},
            }
        }
    }


def detect_dimension_mismatch(
    client: Any,
    index_name: str,
    expected_dims: int,
) -> dict[str, Any]:
    """Check if an existing ES index has a conflicting dense_vector dimension."""
    try:
        mapping = client.indices.get_mapping(index=index_name)
        # ES8: response is {index_name: {"mappings": {...}}}
        index_mapping = (
            mapping.get(index_name) or next(iter(mapping.values()), {})
        )
        props = (
            (index_mapping.get("mappings") or {})
            .get("properties") or {}
        )
        embedding_prop = props.get("embedding") or {}
        actual_dims = embedding_prop.get("dims")
        dimension_match = actual_dims is None or int(actual_dims) == expected_dims
        return {
            "dimension_match": dimension_match,
            "expected_dims": expected_dims,
            "actual_dims": actual_dims,
        }
    except Exception as exc:
        return {
            "dimension_match": None,
            "expected_dims": expected_dims,
            "actual_dims": None,
            "error": _sanitize_error_message(exc),
        }


def ensure_es_index(
    client: Any,
    index_name: str,
    dimensions: int,
) -> dict[str, Any]:
    """Ensure an ES index exists with the correct mapping.

    - Creates the index if missing.
    - If exists, checks dense_vector dimension consistency.
    - Returns a diagnostic dict describing what happened.
    """
    try:
        exists = client.indices.exists(index=index_name)
        # elasticsearch-py 8.x: exists returns a boolean-like HeadApiResponse
        index_exists = bool(exists)
    except Exception as exc:
        return {
            "created": False,
            "exists": None,
            "dimension_match": None,
            "expected_dims": dimensions,
            "actual_dims": None,
            "error": _sanitize_error_message(exc),
        }

    if not index_exists:
        mapping = build_es_index_mapping(dimensions)
        try:
            client.indices.create(index=index_name, body=mapping)
            return {
                "created": True,
                "exists": True,
                "dimension_match": True,
                "expected_dims": dimensions,
                "actual_dims": dimensions,
            }
        except Exception as exc:
            return {
                "created": False,
                "exists": False,
                "dimension_match": None,
                "expected_dims": dimensions,
                "actual_dims": None,
                "error": _sanitize_error_message(exc),
            }

    # Index exists — verify dimension consistency
    mismatch_info = detect_dimension_mismatch(client, index_name, dimensions)
    return {
        "created": False,
        "exists": True,
        "dimension_match": mismatch_info.get("dimension_match"),
        "expected_dims": dimensions,
        "actual_dims": mismatch_info.get("actual_dims"),
    }


# ── Artifact-to-ES Sync ───────────────────────────────────────────────────────


def _es_bulk_upsert(
    client: Any,
    index_name: str,
    docs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bulk upsert (index) documents into ES using the bulk API.
    Each doc must include a '_id' key used as the document id.
    """
    if not docs:
        return {"synced_count": 0, "error_count": 0, "errors": []}

    # Build bulk body: alternating action + source lines
    bulk_body: list[dict[str, Any]] = []
    for doc in docs:
        doc_id = doc.get("_id") or doc.get("node_key") or ""
        body_doc = {key: value for key, value in doc.items() if key != "_id"}
        bulk_body.append({"index": {"_index": index_name, "_id": doc_id}})
        bulk_body.append(body_doc)

    try:
        response = client.bulk(body=bulk_body, refresh=False)
        items = response.get("items") or []
        errors = [
            item
            for item in items
            if (item.get("index") or {}).get("error")
        ]
        return {
            "synced_count": len(items) - len(errors),
            "error_count": len(errors),
            "errors": [
                _sanitize_error_message(str((e.get("index") or {}).get("error")))
                for e in errors[:10]
            ],
        }
    except Exception as exc:
        return {
            "synced_count": 0,
            "error_count": len(docs),
            "errors": [_sanitize_error_message(exc)],
        }


def sync_artifact_to_es(
    client: Any,
    artifact_result: "NodeEmbeddingArtifactResult",
    *,
    tenant_id: str,
    index_name: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync nodes from an artifact bundle into ES via bulk upsert.

    - Reads from the canonical artifact bundle (never writes back to artifact).
    - Uses node_key as the ES document _id (idempotent, repeatable).
    - Only syncs nodes that have a valid embedding vector.
    - dry_run=True: returns what would be synced, but does not call ES.
    """
    bundle = artifact_result.bundle if artifact_result.available else None
    if not isinstance(bundle, Mapping):
        return {
            "synced_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "dry_run": dry_run,
            "errors": [],
            "skip_reason": "artifact_unavailable",
        }

    bundle_key = bundle.get("bundle_key") or {}
    document_id = _normalize_text(bundle_key.get("document_id")) or ""
    version_id = _normalize_text(bundle_key.get("version_id")) or ""
    routing_index_version = _normalize_text(bundle_key.get("routing_index_version")) or "v1"
    embedding_spec_id = (
        _normalize_text(bundle_key.get("embedding_spec_id"))
        or _normalize_text(artifact_result.embedding_spec_id)
        or ""
    )
    synced_at = datetime.now(timezone.utc).isoformat()

    docs: list[dict[str, Any]] = []
    skipped_count = 0
    for node in _bundle_nodes(bundle):
        if not isinstance(node, Mapping):
            skipped_count += 1
            continue
        node_key = _normalize_text(node.get("node_key"))
        node_id = _normalize_text(node.get("node_id"))
        if not node_key:
            skipped_count += 1
            continue
        embedding = node.get("embedding")
        if not isinstance(embedding, Sequence) or isinstance(embedding, (str, bytes, bytearray)) or not embedding:
            skipped_count += 1
            continue
        vector = [float(v) for v in embedding]
        docs.append({
            "_id": node_key,
            "tenant_id": tenant_id,
            # workspace_id is optional/reserved — not populated here
            "document_id": _normalize_text(node.get("document_id")) or document_id,
            "version_id": _normalize_text(node.get("version_id")) or version_id,
            "node_id": node_id or "",
            "node_key": node_key,
            "embedding_spec_id": embedding_spec_id,
            "routing_index_version": routing_index_version,
            "page_start": node.get("page_start"),
            "page_end": node.get("page_end"),
            "title": _normalize_text(node.get("title")) or "",
            "breadcrumb": _normalize_text(node.get("breadcrumb")) or "",
            "summary": _normalize_text(node.get("summary")) or "",
            "section_text": _normalize_text(node.get("section_text")) or "",
            "section_text_checksum": _json_hash(_normalize_text(node.get("section_text")) or ""),
            "text": _normalize_text(node.get("text")) or "",
            "embedding": vector,
            "synced_at": synced_at,
        })

    if dry_run:
        return {
            "synced_count": 0,
            "skipped_count": skipped_count,
            "error_count": 0,
            "dry_run": True,
            "would_sync_count": len(docs),
            "errors": [],
        }

    bulk_result = _es_bulk_upsert(client, index_name, docs)
    return {
        "synced_count": bulk_result["synced_count"],
        "skipped_count": skipped_count,
        "error_count": bulk_result["error_count"],
        "dry_run": False,
        "errors": bulk_result["errors"],
    }


def sync_bundles_to_es(
    artifact_results: list["NodeEmbeddingArtifactResult"],
    *,
    client: Any,
    tenant_id: str,
    index_prefix: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync multiple artifact bundles to ES.

    For each bundle:
    - Derives the correct index name from bundle_key.
    - Calls ensure_es_index to create the index if missing.
    - Calls sync_artifact_to_es for upsert.

    Returns aggregated sync stats.
    """
    resolved_prefix = _normalize_text(index_prefix) or DEFAULT_NODE_ES_INDEX_PREFIX
    total_synced = 0
    total_skipped = 0
    total_errors = 0
    index_results: list[dict[str, Any]] = []

    for artifact_result in artifact_results:
        bundle = artifact_result.bundle if artifact_result.available else None
        if not isinstance(bundle, Mapping):
            index_results.append({
                "skip_reason": "artifact_unavailable",
                "synced_count": 0,
            })
            continue

        bundle_key = bundle.get("bundle_key") or {}
        manifest = bundle.get("manifest") or {}
        routing_index_version = _normalize_text(bundle_key.get("routing_index_version")) or "v1"
        embedding_spec_id = (
            _normalize_text(bundle_key.get("embedding_spec_id"))
            or _normalize_text(artifact_result.embedding_spec_id)
            or "node-emb"
        )
        dimensions = int(manifest.get("dimensions") or 0)
        index_name = es_index_name_for_embedding_bundle(
            routing_index_version=routing_index_version,
            embedding_spec_id=embedding_spec_id,
            index_prefix=resolved_prefix,
        )

        ensure_result = ensure_es_index(client, index_name, dimensions) if dimensions > 0 else {"skip_reason": "dimensions_unknown"}
        sync_result = sync_artifact_to_es(
            client,
            artifact_result,
            tenant_id=tenant_id,
            index_name=index_name,
            dry_run=dry_run,
        )
        index_results.append({
            "index_name": index_name,
            "ensure": ensure_result,
            **sync_result,
        })
        total_synced += sync_result.get("synced_count", 0)
        total_skipped += sync_result.get("skipped_count", 0)
        total_errors += sync_result.get("error_count", 0)

    return {
        "dry_run": dry_run,
        "bundle_count": len(artifact_results),
        "total_synced_count": total_synced,
        "total_skipped_count": total_skipped,
        "total_error_count": total_errors,
        "index_results": index_results,
    }


# ─────────────────────────────────────────────────────────────────────────────


class EsNodeDenseSearchBackend(NodeDenseSearchBackend):
    dense_source = NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW

    def __init__(
        self,
        *,
        exact_backend: ExactScanNodeDenseSearchBackend | None = None,
        es_client: Any | None = None,
    ) -> None:
        self.exact_backend = exact_backend or ExactScanNodeDenseSearchBackend()
        self.es_client = es_client

    def _client(self, settings: Any) -> tuple[Any | None, str | None]:
        if self.es_client is not None:
            return self.es_client, None
        try:
            from elasticsearch import Elasticsearch  # type: ignore
        except Exception:
            return None, "es_dependency_unavailable"
        url = _normalize_text(getattr(settings, "routing_node_es_url", None))
        if not url:
            return None, "es_url_missing"
        try:
            return Elasticsearch(url), None
        except Exception as exc:
            return None, f"es_client_unavailable:{type(exc).__name__}"

    @staticmethod
    def _node_keys_for_artifact(artifact_result: NodeEmbeddingArtifactResult) -> list[str]:
        bundle = artifact_result.bundle if artifact_result.available else None
        if not isinstance(bundle, Mapping):
            return []
        keys: list[str] = []
        for node in bundle.get("nodes") or []:
            if isinstance(node, Mapping) and (node_key := _normalize_text(node.get("node_key"))):
                keys.append(node_key)
        return keys

    def _fallback_exact(
        self,
        prepared: PreparedDenseSearch,
        *,
        es_fallback_reason: str,
    ) -> NodeDenseSearchResult:
        exact = self.exact_backend._search_prepared(
            prepared,
            requested_dense_source=self.dense_source,
            es={"enabled": False, "fallback_reason": es_fallback_reason},
        )
        return replace(
            exact,
            fallback_reason=exact.fallback_reason or es_fallback_reason,
            es={"enabled": False, "fallback_reason": es_fallback_reason},
        )

    def _unavailable_result(
        self,
        *,
        fallback_reason: str,
        query_embedding_dimensions: int | None = None,
        searched_indices: list[str] | None = None,
    ) -> NodeDenseSearchResult:
        return NodeDenseSearchResult(
            dense_scores={},
            dense_source=self.dense_source,
            requested_dense_source=self.dense_source,
            enabled=False,
            fallback_reason=fallback_reason,
            query_embedding_dimensions=query_embedding_dimensions,
            artifacts=[],
            es={
                "enabled": False,
                "used": False,
                "searched_indices": searched_indices or [],
                "fallback_reason": fallback_reason,
            },
        )

    def search(
        self,
        *,
        query: str,
        node_corpora: Sequence[Mapping[str, Any]],
        embedding_mode: str | None = None,
        provider_config: Mapping[str, Any] | None = None,
        embedding_config: Mapping[str, Any] | None = None,
        settings_obj: Any | None = None,
    ) -> NodeDenseSearchResult:
        settings = settings_obj or get_settings()
        normalized_query = _normalize_text(query)
        if not normalized_query:
            return self._unavailable_result(fallback_reason="query_empty")

        resolved_config = dict(
            embedding_config
            or resolve_embedding_config(
                provider_config=dict(provider_config or {}),
                embedding_mode=embedding_mode,
            )
        )
        if not resolved_config.get("enabled"):
            fallback_reason = _normalize_text(resolved_config.get("fallback_reason")) or "embedding_unavailable"
            return self._unavailable_result(fallback_reason=f"embedding_unavailable:{fallback_reason}")

        embedding_client = (
            self.exact_backend.embedding_client
            or self.exact_backend.artifact_store.embedding_client
            or OpenAICompatibleEmbeddingClient.from_embedding_config(resolved_config)
        )
        if embedding_client is None:
            return self._unavailable_result(fallback_reason="embedding_client_unavailable")
        try:
            query_vectors = embedding_client.embed([normalized_query])
        except Exception as exc:
            return self._unavailable_result(fallback_reason=_embedding_error_reason(exc))
        if not query_vectors or not query_vectors[0]:
            return self._unavailable_result(fallback_reason="query_embedding_empty")
        query_vector = [float(value) for value in query_vectors[0]]
        query_dimensions = len(query_vector)

        if not bool(getattr(settings, "routing_node_es_enabled", False)):
            return self._unavailable_result(
                fallback_reason="es_required_unavailable:es_disabled",
                query_embedding_dimensions=query_dimensions,
            )

        client, client_error = self._client(settings)
        if client is None:
            return self._unavailable_result(
                fallback_reason=f"es_required_unavailable:{client_error or 'es_client_unavailable'}",
                query_embedding_dimensions=query_dimensions,
            )

        index_prefix = _normalize_text(getattr(settings, "routing_node_es_index_prefix", None)) or DEFAULT_NODE_ES_INDEX_PREFIX
        dense_scores: dict[str, float] = {}
        searched_indices: list[str] = []
        try:
            embedding_spec_id = embedding_spec_id_for_config(resolved_config)
            for corpus in node_corpora:
                if not isinstance(corpus, Mapping):
                    continue
                manual = corpus.get("manual") if isinstance(corpus.get("manual"), Mapping) else {}
                index_name = es_index_name_for_embedding_bundle(
                    routing_index_version=(manual or {}).get("routing_index_version") or "v1",
                    embedding_spec_id=embedding_spec_id,
                    index_prefix=index_prefix,
                )
                nodes = [node for node in corpus.get("nodes") or [] if isinstance(node, Mapping)]
                node_keys = [
                    key
                    for node in nodes
                    if (key := _normalize_text(node.get("node_key")))
                ]
                if not node_keys:
                    continue
                searched_indices.append(index_name)

                # Build metadata filter: tenant_id, document_id, version_id, embedding_spec_id
                # workspace_id is optional — not included in mandatory filter
                filter_clauses: list[dict[str, Any]] = [
                    {"terms": {"node_key": node_keys}},
                ]
                # Add document/version filter when available from bundle_key
                document_id = _normalize_text((manual or {}).get("document_id"))
                version_id = _normalize_text((manual or {}).get("version_id"))
                if document_id:
                    filter_clauses.append({"term": {"document_id": document_id}})
                if version_id:
                    filter_clauses.append({"term": {"version_id": version_id}})
                filter_clauses.append({"term": {"embedding_spec_id": embedding_spec_id}})

                lexical_query = {
                    "bool": {
                        "filter": filter_clauses,
                        "should": [
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": [
                                        "section_text^8",
                                        "title^5",
                                        "breadcrumb^4",
                                        "summary^3",
                                        "text^2",
                                    ],
                                    "type": "best_fields",
                                }
                            },
                            {"match_phrase": {"section_text": {"query": query, "boost": 12}}},
                            {"match_phrase": {"text": {"query": query, "boost": 6}}},
                        ],
                        "minimum_should_match": 0,
                    }
                }

                body = {
                    "size": len(node_keys),
                    "query": {
                        "script_score": {
                            "query": lexical_query,
                            "script": {
                                "source": """
                                    double dense = (cosineSimilarity(params.query_vector, 'embedding') + 1.0) / 2.0;
                                    double lexical = Math.min(_score, 20.0) / 20.0;
                                    return (0.65 * lexical) + (0.35 * dense);
                                """,
                                "params": {"query_vector": query_vector},
                            },
                        }
                    },
                }
                response = client.search(index=index_name, body=body)
                hits = ((response or {}).get("hits") or {}).get("hits") or []
                for hit in hits:
                    if not isinstance(hit, Mapping):
                        continue
                    source = hit.get("_source") if isinstance(hit.get("_source"), Mapping) else {}
                    node_key = _normalize_text(source.get("node_key") or hit.get("_id"))
                    score = _normalize_float(hit.get("_score"))
                    if node_key and score is not None:
                        dense_scores[node_key] = score
        except Exception as exc:
            return self._unavailable_result(
                fallback_reason=f"es_required_unavailable:es_search_error:{type(exc).__name__}",
                query_embedding_dimensions=query_dimensions,
                searched_indices=searched_indices,
            )

        if not dense_scores:
            return self._unavailable_result(
                fallback_reason="es_required_unavailable:es_empty_result",
                query_embedding_dimensions=query_dimensions,
                searched_indices=searched_indices,
            )

        return NodeDenseSearchResult(
            dense_scores=dense_scores,
            dense_source=self.dense_source,
            requested_dense_source=self.dense_source,
            enabled=True,
            fallback_reason=None,
            query_embedding_dimensions=query_dimensions,
            artifacts=[],
            es={
                "enabled": True,
                "used": True,
                "index_prefix": index_prefix,
                "searched_indices": searched_indices,
                "fallback_reason": None,
            },
        )


__all__ = [
    "DEFAULT_NODE_ES_INDEX_PREFIX",
    "DEFAULT_OPENAI_COMPATIBLE_EMBEDDING_BATCH_SIZE",
    "EsNodeDenseSearchBackend",
    "ExactScanNodeDenseSearchBackend",
    "NODE_EMBEDDING_ARTIFACT_LAYOUT_SINGLE_FILE",
    "NODE_EMBEDDING_ARTIFACT_SCHEMA_VERSION",
    "NODE_EMBEDDING_ARTIFACT_STATUS_COMPLETE",
    "NODE_EMBEDDING_ARTIFACT_STATUS_FAILED",
    "NODE_EMBEDDING_ARTIFACT_STATUS_PARTIAL",
    "NODE_EMBEDDING_DENSE_SOURCE_ARTIFACT_EXACT",
    "NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW",
    "NODE_EMBEDDING_DENSE_SOURCE_SPARSE",
    "NODE_EMBEDDING_TEXT_SCHEMA_VERSION",
    "NodeDenseSearchBackend",
    "NodeDenseSearchResult",
    "NodeEmbeddingArtifactResult",
    "NodeEmbeddingArtifactStore",
    "OpenAICompatibleEmbeddingClient",
    "build_es_index_mapping",
    "build_node_embedding_text",
    "detect_dimension_mismatch",
    "embedding_spec_id_for_config",
    "embedding_runtime_options",
    "ensure_es_index",
    "es_index_name_for_embedding_bundle",
    "sync_artifact_to_es",
    "sync_bundles_to_es",
]
