#!/usr/bin/env python3
"""node_embedding_es_maintenance.py — ES shadow backend maintenance CLI.

Actions:
  check  — Report ES availability, index list, mapping, and doc counts.
  sync   — Sync embedding artifacts from canonical artifact store into ES.
  query  — Run a sample vector query against ES shadow index.

All actions are read-only safe unless --action sync --execute is passed.
ES must be explicitly enabled (ROUTING_NODE_ES_ENABLED=true) and installed
(pip install .[es]) to communicate with a real ES cluster.

If ES is not enabled or the elasticsearch package is missing, the script
reports the reason and exits with a Conditional-GO status.

NOTE: This script does NOT touch any live path, chat service, compliance
service, API contract, SSE contract, or evidence layer.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.services.node_embedding_service import (
    DEFAULT_NODE_ES_INDEX_PREFIX,
    NodeEmbeddingArtifactResult,
    build_es_index_mapping,
    detect_dimension_mismatch,
    ensure_es_index,
    es_index_name_for_embedding_bundle,
    sync_artifact_to_es,
    sync_bundles_to_es,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _masked_url(url: str | None) -> str | None:
    """Mask credentials in a URL for safe logging."""
    if not url:
        return url
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, host = rest.split("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def _json_out(data: Any, indent: int = 2) -> str:
    return json.dumps(data, ensure_ascii=False, indent=indent, default=str)


def _get_es_client(settings: Any) -> tuple[Any | None, str | None]:
    """Attempt to build an ES client from settings.

    Returns (client, None) on success, (None, reason) on failure.
    Does NOT raise.
    """
    if not getattr(settings, "routing_node_es_enabled", False):
        return None, "es_disabled"
    try:
        from elasticsearch import Elasticsearch  # type: ignore
    except ImportError:
        return None, "es_dependency_unavailable (install: pip install .[es])"
    url = (getattr(settings, "routing_node_es_url", "") or "").strip()
    if not url:
        return None, "es_url_missing (set ROUTING_NODE_ES_URL)"
    try:
        client = Elasticsearch(url)
        return client, None
    except Exception as exc:
        return None, f"es_client_init_error:{type(exc).__name__}:{exc}"


# ── Check action ──────────────────────────────────────────────────────────────


def _action_check(args: argparse.Namespace, settings: Any) -> dict[str, Any]:
    """Report ES availability, index list, mapping, and doc counts."""
    client, client_error = _get_es_client(settings)
    index_prefix = (
        getattr(settings, "routing_node_es_index_prefix", None)
        or DEFAULT_NODE_ES_INDEX_PREFIX
    )
    result: dict[str, Any] = {
        "action": "check",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "routing_node_es_enabled": getattr(settings, "routing_node_es_enabled", False),
            "routing_node_es_url": _masked_url(getattr(settings, "routing_node_es_url", "")),
            "routing_node_es_index_prefix": index_prefix,
        },
        "es_available": client is not None,
        "es_unavailable_reason": client_error,
        "real_es_verified": False,
    }

    if client is None:
        result["gate"] = "Conditional GO — mock/no-ES environment"
        result["note"] = "真实 ES 未验证 (Real ES not verified)"
        return result

    # Ping ES
    try:
        ping_ok = bool(client.ping())
        result["es_ping"] = ping_ok
        if not ping_ok:
            result["es_available"] = False
            result["es_unavailable_reason"] = "es_ping_failed"
            result["gate"] = "NO-GO — ES ping failed"
            return result
    except Exception as exc:
        result["es_ping_error"] = str(exc)
        result["gate"] = "NO-GO — ES ping exception"
        return result

    # List indices matching prefix
    try:
        cat_response = client.cat.indices(index=f"{index_prefix}*", format="json")
        indices = [
            {
                "index": row.get("index"),
                "docs_count": row.get("docs.count"),
                "store_size": row.get("store.size"),
                "health": row.get("health"),
            }
            for row in (cat_response or [])
            if isinstance(row, dict)
        ]
        result["indices"] = indices
        result["index_count"] = len(indices)
    except Exception as exc:
        result["indices_error"] = str(exc)
        result["indices"] = []
        result["index_count"] = 0

    result["real_es_verified"] = True
    result["gate"] = "GO — ES available and responding"
    return result


# ── Sync action ───────────────────────────────────────────────────────────────


def _action_sync(args: argparse.Namespace, settings: Any) -> dict[str, Any]:
    """Sync embedding artifact bundles from storage into ES.

    Reads artifact bundle paths from --bundle-paths (JSON array of paths).
    Each path must be a bundle.json file from the canonical artifact store.
    """
    dry_run = args.dry_run
    client, client_error = _get_es_client(settings)
    index_prefix = (
        getattr(settings, "routing_node_es_index_prefix", None)
        or DEFAULT_NODE_ES_INDEX_PREFIX
    )
    result: dict[str, Any] = {
        "action": "sync",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "config": {
            "routing_node_es_enabled": getattr(settings, "routing_node_es_enabled", False),
            "routing_node_es_url": _masked_url(getattr(settings, "routing_node_es_url", "")),
            "routing_node_es_index_prefix": index_prefix,
        },
        "es_available": client is not None,
        "es_unavailable_reason": client_error,
        "real_es_verified": False,
    }

    if client is None and not dry_run:
        result["gate"] = "Conditional GO — no ES runtime, sync skipped"
        result["note"] = "真实 ES 未验证 (Real ES not verified)"
        return result

    # Load bundle files
    bundle_paths_arg = getattr(args, "bundle_paths", None)
    if not bundle_paths_arg:
        result["error"] = "No --bundle-paths provided. Pass a JSON array of bundle.json file paths."
        result["gate"] = "NO-GO — no bundle paths"
        return result

    try:
        bundle_paths: list[str] = json.loads(bundle_paths_arg)
    except json.JSONDecodeError:
        # Maybe a single path
        bundle_paths = [bundle_paths_arg]

    artifact_results: list[NodeEmbeddingArtifactResult] = []
    tenant_id = getattr(args, "tenant_id", None) or "shadow"

    for path_str in bundle_paths:
        bundle_path = Path(path_str)
        if not bundle_path.exists():
            artifact_results.append(
                NodeEmbeddingArtifactResult(
                    available=False,
                    fallback_reason=f"bundle_file_not_found:{path_str}",
                )
            )
            continue
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            if not isinstance(bundle, dict):
                raise ValueError("not a dict")
            bundle_key = bundle.get("bundle_key") or {}
            artifact_results.append(
                NodeEmbeddingArtifactResult(
                    available=True,
                    bundle=bundle,
                    uri=str(bundle_path),
                    object_path=str(bundle_path),
                    embedding_spec_id=bundle_key.get("embedding_spec_id"),
                )
            )
        except Exception as exc:
            artifact_results.append(
                NodeEmbeddingArtifactResult(
                    available=False,
                    fallback_reason=f"bundle_load_error:{type(exc).__name__}",
                )
            )

    loaded_count = sum(1 for a in artifact_results if a.available)
    result["bundle_count"] = len(artifact_results)
    result["bundle_loaded_count"] = loaded_count

    if dry_run or client is None:
        # Run in dry-run mode (no actual ES writes)
        sync_result = sync_bundles_to_es(
            artifact_results,
            client=client or _FakeDryRunClient(),
            tenant_id=tenant_id,
            index_prefix=index_prefix,
            dry_run=True,
        )
        result["sync"] = sync_result
        result["note"] = "真实 ES 未验证 (Real ES not verified — dry_run or no ES client)"
        result["gate"] = "Conditional GO — dry-run sync completed"
        return result

    sync_result = sync_bundles_to_es(
        artifact_results,
        client=client,
        tenant_id=tenant_id,
        index_prefix=index_prefix,
        dry_run=False,
    )
    result["sync"] = sync_result
    result["real_es_verified"] = True
    total_errors = sync_result.get("total_error_count", 0)
    result["gate"] = "GO — sync completed" if total_errors == 0 else f"Conditional GO — {total_errors} errors during sync"
    return result


class _FakeDryRunClient:
    """Minimal fake client used in dry-run mode when no real ES is available."""

    @staticmethod
    def bulk(**_kwargs) -> dict:
        return {"items": []}

    @staticmethod
    def indices():
        return _FakeDryRunIndices()


class _FakeDryRunIndices:
    @staticmethod
    def exists(**_kwargs) -> bool:
        return False

    @staticmethod
    def create(**_kwargs) -> dict:
        return {}

    @staticmethod
    def get_mapping(**_kwargs) -> dict:
        return {}


# ── Query action ──────────────────────────────────────────────────────────────


def _action_query(args: argparse.Namespace, settings: Any) -> dict[str, Any]:
    """Run a test vector query against ES shadow index.

    Requires --index-name and optionally --query-vector (JSON float array).
    """
    client, client_error = _get_es_client(settings)
    result: dict[str, Any] = {
        "action": "query",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "es_available": client is not None,
        "es_unavailable_reason": client_error,
        "real_es_verified": False,
    }

    if client is None:
        result["gate"] = "Conditional GO — no ES runtime"
        result["note"] = "真实 ES 未验证 (Real ES not verified)"
        return result

    index_name = getattr(args, "index_name", None)
    if not index_name:
        result["error"] = "No --index-name provided"
        result["gate"] = "NO-GO — missing index name"
        return result

    query_vector_arg = getattr(args, "query_vector", None)
    if not query_vector_arg:
        result["error"] = "No --query-vector provided"
        result["gate"] = "NO-GO — missing query vector"
        return result

    try:
        query_vector: list[float] = json.loads(query_vector_arg)
        if not isinstance(query_vector, list) or not query_vector:
            raise ValueError("query_vector must be a non-empty JSON float array")
    except (json.JSONDecodeError, ValueError) as exc:
        result["error"] = str(exc)
        result["gate"] = "NO-GO — invalid query vector"
        return result

    top_k = getattr(args, "top_k", None) or 5

    try:
        body = {
            "size": int(top_k),
            "query": {
                "script_score": {
                    "query": {"match_all": {}},
                    "script": {
                        "source": "(cosineSimilarity(params.query_vector, 'embedding') + 1.0) / 2.0",
                        "params": {"query_vector": query_vector},
                    },
                }
            },
            "_source": ["node_key", "document_id", "version_id", "tenant_id", "embedding_spec_id"],
        }
        response = client.search(index=index_name, body=body)
        hits = ((response or {}).get("hits") or {}).get("hits") or []
        result["hits"] = [
            {
                "node_key": (hit.get("_source") or {}).get("node_key") or hit.get("_id"),
                "score": hit.get("_score"),
                "document_id": (hit.get("_source") or {}).get("document_id"),
                "version_id": (hit.get("_source") or {}).get("version_id"),
                "embedding_spec_id": (hit.get("_source") or {}).get("embedding_spec_id"),
            }
            for hit in hits
        ]
        result["hit_count"] = len(result["hits"])
        result["real_es_verified"] = True
        result["gate"] = "GO — ES query returned results" if result["hits"] else "Conditional GO — ES query returned 0 hits"
    except Exception as exc:
        result["error"] = str(exc)
        result["gate"] = "NO-GO — ES query failed"

    return result


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "ES shadow backend maintenance for PageIndex node embeddings.\n"
            "ES is disabled-by-default; does not touch live path.\n"
        )
    )
    parser.add_argument(
        "--action",
        choices=("check", "sync", "query"),
        default="check",
        help="Maintenance action to run (default: check).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="For sync: report what would be synced without writing to ES.",
    )
    parser.add_argument(
        "--index-prefix",
        default=None,
        help="Override ROUTING_NODE_ES_INDEX_PREFIX from env.",
    )
    parser.add_argument(
        "--bundle-paths",
        default=None,
        help=(
            "JSON array (or single path) of bundle.json file paths "
            "to sync into ES. Required for --action sync."
        ),
    )
    parser.add_argument(
        "--tenant-id",
        default="shadow",
        help="Tenant ID to use when syncing artifacts to ES (default: shadow).",
    )
    parser.add_argument(
        "--index-name",
        default=None,
        help="ES index name. Required for --action query.",
    )
    parser.add_argument(
        "--query-vector",
        default=None,
        help="JSON float array to use as query vector for --action query.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Top-K results for --action query (default: 5).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write JSON result to this file path instead of stdout.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()

    # Allow --index-prefix to override env
    if args.index_prefix:
        # We patch the attribute on the settings object temporarily
        object.__setattr__(settings, "routing_node_es_index_prefix", args.index_prefix)

    if args.action == "check":
        result = _action_check(args, settings)
    elif args.action == "sync":
        result = _action_sync(args, settings)
    elif args.action == "query":
        result = _action_query(args, settings)
    else:
        result = {"error": f"Unknown action: {args.action}"}

    output = _json_out(result)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
