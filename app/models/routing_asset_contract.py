"""Routing asset v1 contract and compatibility helpers.

The routing asset is a data-plane artifact, not a live router decision surface.
In v1:

- ``routing_index_version`` / ``schema_version`` identify the artifact contract.
- ``base_nodes`` are the persisted routing-node rows and the JSON base payload.
- ``route_docs``, ``synthetic_queries``, and ``embeddings`` are deferred future stages.

Compatibility rule:

- legacy payloads that omit the newer metadata fields are read as v1 payloads
  with safe defaults.
- the helper keeps unknown fields intact so newer writers remain forward
  compatible with older readers.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


ROUTING_ASSET_SCHEMA_VERSION = "v1"
ROUTING_ASSET_READINESS_STAGES = ("base_nodes", "route_docs", "synthetic_queries", "embeddings")
ROUTING_ASSET_READY = "ready"
ROUTING_ASSET_DEFERRED = "deferred"
ROUTING_ASSET_PENDING = "pending"
ROUTING_ASSET_FAILED = "failed"
ROUTING_ASSET_UNKNOWN = "unknown"
ROUTING_ASSET_VALID_READINESS_VALUES = frozenset(
    {
        ROUTING_ASSET_READY,
        ROUTING_ASSET_DEFERRED,
        ROUTING_ASSET_PENDING,
        ROUTING_ASSET_FAILED,
        ROUTING_ASSET_UNKNOWN,
    }
)
ROUTING_ASSET_NODE_OPTIONAL_FIELDS = ("contrastive_summary", "aliases_json", "keywords_json", "manual_profile_text")


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _normalize_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_readiness_value(value: Any, *, fallback: str) -> str:
    text = _normalize_text(value)
    if text is None:
        return fallback
    lowered = text.lower()
    if lowered in ROUTING_ASSET_VALID_READINESS_VALUES:
        return lowered
    return fallback


def routing_asset_readiness_defaults(*, base_nodes_state: str = ROUTING_ASSET_READY) -> dict[str, str]:
    return {
        "base_nodes": _normalize_readiness_value(base_nodes_state, fallback=ROUTING_ASSET_READY),
        "route_docs": ROUTING_ASSET_DEFERRED,
        "synthetic_queries": ROUTING_ASSET_DEFERRED,
        "embeddings": ROUTING_ASSET_DEFERRED,
    }


def routing_asset_readiness_for_version(
    *,
    routing_index_status: str | None,
    routing_index_path: str | None,
) -> dict[str, str]:
    normalized_status = _normalize_text(routing_index_status)
    if normalized_status == "index_ready":
        base_nodes_state = ROUTING_ASSET_READY if _normalize_text(routing_index_path) else ROUTING_ASSET_UNKNOWN
    elif normalized_status == "failed":
        base_nodes_state = ROUTING_ASSET_FAILED
    elif normalized_status in {"uploaded", "queued", "parsing"}:
        base_nodes_state = ROUTING_ASSET_PENDING
    else:
        base_nodes_state = ROUTING_ASSET_UNKNOWN
    return routing_asset_readiness_defaults(base_nodes_state=base_nodes_state)


def normalize_routing_asset_readiness(
    readiness: Mapping[str, Any] | None,
    *,
    base_nodes_state: str = ROUTING_ASSET_READY,
) -> dict[str, str]:
    normalized = routing_asset_readiness_defaults(base_nodes_state=base_nodes_state)
    if not isinstance(readiness, Mapping):
        return normalized

    for key, value in readiness.items():
        if key in ROUTING_ASSET_READINESS_STAGES:
            normalized[key] = _normalize_readiness_value(value, fallback=normalized[key])
        else:
            normalized[key] = value
    return normalized


def normalize_routing_index_nodes(nodes: Any) -> list[dict[str, Any]]:
    if isinstance(nodes, Mapping):
        node_items = [nodes]
    elif isinstance(nodes, list):
        node_items = nodes
    else:
        node_items = []

    normalized_nodes: list[dict[str, Any]] = []
    for node in node_items:
        if not isinstance(node, Mapping):
            continue
        normalized = dict(node)
        normalized["node_id"] = _normalize_text(normalized.get("node_id"))
        normalized["parent_node_id"] = _normalize_text(normalized.get("parent_node_id"))
        normalized["depth"] = _normalize_optional_int(normalized.get("depth")) or 0
        normalized["title"] = _normalize_text(normalized.get("title"))
        normalized["breadcrumb"] = _normalize_text(normalized.get("breadcrumb"))
        normalized["page_start"] = _normalize_optional_int(normalized.get("page_start"))
        normalized["page_end"] = _normalize_optional_int(normalized.get("page_end"))
        normalized["route_summary"] = _normalize_text(normalized.get("route_summary"))
        normalized["contrastive_summary"] = _normalize_text(normalized.get("contrastive_summary"))
        normalized["aliases_json"] = _normalize_json_text(normalized.get("aliases_json"))
        normalized["keywords_json"] = _normalize_json_text(normalized.get("keywords_json"))
        normalized["manual_profile_text"] = _normalize_text(normalized.get("manual_profile_text"))
        normalized_nodes.append(normalized)
    return normalized_nodes


def normalize_routing_index_payload(
    payload: Any,
    *,
    document_label: str | None = None,
    source_doc_name: str | None = None,
    document_id: str | None = None,
    version_id: str | None = None,
    schema_version: str | None = None,
    base_nodes_state: str = ROUTING_ASSET_READY,
) -> dict[str, Any]:
    normalized = dict(payload) if isinstance(payload, Mapping) else {}

    resolved_schema_version = _normalize_text(
        schema_version or normalized.get("schema_version") or normalized.get("routing_index_version")
    ) or ROUTING_ASSET_SCHEMA_VERSION
    normalized["schema_version"] = resolved_schema_version
    normalized["routing_index_version"] = resolved_schema_version
    normalized["document_label"] = (
        _normalize_text(normalized.get("document_label"))
        or _normalize_text(document_label)
        or _normalize_text(normalized.get("source_doc_name"))
        or _normalize_text(source_doc_name)
    )
    normalized["source_doc_name"] = _normalize_text(normalized.get("source_doc_name")) or _normalize_text(source_doc_name)
    normalized["document_id"] = _normalize_text(normalized.get("document_id")) or _normalize_text(document_id)
    normalized["version_id"] = _normalize_text(normalized.get("version_id")) or _normalize_text(version_id)
    normalized["readiness"] = normalize_routing_asset_readiness(
        normalized.get("readiness"),
        base_nodes_state=base_nodes_state,
    )
    normalized["nodes"] = normalize_routing_index_nodes(normalized.get("nodes"))

    node_count = _normalize_optional_int(normalized.get("node_count"))
    if node_count is None:
        node_count = len(normalized["nodes"])
    normalized["node_count"] = node_count
    return normalized


__all__ = [
    "ROUTING_ASSET_SCHEMA_VERSION",
    "ROUTING_ASSET_READINESS_STAGES",
    "ROUTING_ASSET_READY",
    "ROUTING_ASSET_DEFERRED",
    "ROUTING_ASSET_PENDING",
    "ROUTING_ASSET_FAILED",
    "ROUTING_ASSET_UNKNOWN",
    "ROUTING_ASSET_VALID_READINESS_VALUES",
    "ROUTING_ASSET_NODE_OPTIONAL_FIELDS",
    "normalize_routing_asset_readiness",
    "normalize_routing_index_nodes",
    "normalize_routing_index_payload",
    "routing_asset_readiness_defaults",
    "routing_asset_readiness_for_version",
]
