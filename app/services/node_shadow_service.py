from __future__ import annotations

import json
import re
import time
from collections import Counter, OrderedDict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import DocumentRoutingNode
from app.services.pageindex_service import load_structure_file
from app.services.node_embedding_service import (
    NodeDenseSearchBackend,
)
from app.services.provider_service import resolve_embedding_config
from app.services.routing_consumer_service import (
    MANUAL_GATE_INVENTORY_SOURCE_PRIORITY,
    tokenize_routing_text,
)
from app.services.section_text_provider import SectionTextProvider
from app.services.storage_service import local_artifact_path, read_document_routing_index
from pageindex.utils import get_page_tokens, get_text_of_pdf_pages_with_labels


NODE_SHADOW_SCORE_VERSION = "node_shadow_r1.v1"
NODE_SHADOW_REPORT_SCHEMA_VERSION = "node_shadow_report_v1"
NODE_CORPUS_SOURCE_PRIORITY = MANUAL_GATE_INVENTORY_SOURCE_PRIORITY
NODE_CORPUS_PRIMARY_SOURCE = "document_routing_nodes"
NODE_CORPUS_METADATA_ONLY_SOURCE = "metadata_only"
NODE_DENSE_WEIGHT = 0.3
NODE_LEXICAL_WEIGHT = 0.7
NODE_SECTION_TEXT_MAX_CHARS = 200_000
NODE_PAGE_TOKEN_CACHE_LIMIT = 4
_CJK_PHRASE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]{4,}")
_PAGE_TOKEN_CACHE: OrderedDict[str, list[tuple[str, int]] | None] = OrderedDict()


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(score, 1.0))


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _manual_key(manual_ref: Mapping[str, Any]) -> str:
    explicit = _normalize_text(manual_ref.get("manual_key"))
    if explicit:
        return explicit
    return f"{manual_ref.get('document_id') or 'unknown'}:{manual_ref.get('version_id') or 'unknown'}"


def _page_span(page_start: Any, page_end: Any) -> int | None:
    normalized_start = _normalize_optional_int(page_start)
    normalized_end = _normalize_optional_int(page_end)
    if normalized_start is None or normalized_end is None or normalized_end < normalized_start:
        return None
    return normalized_end - normalized_start + 1


def _safe_json_loads(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _manual_metadata_text(manual_ref: Mapping[str, Any]) -> str:
    parts = [
        manual_ref.get("document_label"),
        manual_ref.get("version_label"),
        manual_ref.get("display_name"),
        manual_ref.get("source_filename"),
    ]
    return " ".join(str(part) for part in parts if _normalize_text(part))


def _route_doc_from_node(
    manual_ref: Mapping[str, Any],
    node: Mapping[str, Any],
    *,
    corpus_source: str,
    original_index: int,
) -> dict[str, Any] | None:
    node_id = _normalize_text(node.get("node_id"))
    if node_id is None:
        return None

    manual_key = _manual_key(manual_ref)
    page_start = _normalize_optional_int(node.get("page_start"))
    page_end = _normalize_optional_int(node.get("page_end"))
    route_doc = {
        "manual_key": manual_key,
        "document_id": _normalize_text(manual_ref.get("document_id")),
        "version_id": _normalize_text(manual_ref.get("version_id")),
        "document_label": _normalize_text(manual_ref.get("document_label")),
        "version_label": _normalize_text(manual_ref.get("version_label")),
        "display_name": _normalize_text(manual_ref.get("display_name")),
        "source_filename": _normalize_text(manual_ref.get("source_filename")),
        "routing_index_status": _normalize_text(manual_ref.get("routing_index_status")),
        "routing_index_path_present": _normalize_text(manual_ref.get("routing_index_path")) is not None,
        "routing_index_version": _normalize_text(manual_ref.get("routing_index_version")),
        "node_id": node_id,
        "node_key": f"{manual_key}:{node_id}",
        "parent_node_id": _normalize_text(node.get("parent_node_id")),
        "title": _normalize_text(node.get("title")),
        "breadcrumb": _normalize_text(node.get("breadcrumb")),
        "page_start": page_start,
        "page_end": page_end,
        "page_span": _page_span(page_start, page_end),
        "depth": _normalize_optional_int(node.get("depth")) or 0,
        "route_summary": _normalize_text(node.get("route_summary")),
        "contrastive_summary": _normalize_text(node.get("contrastive_summary")),
        "aliases": _safe_json_loads(node.get("aliases_json")),
        "keywords": _safe_json_loads(node.get("keywords_json")),
        "manual_profile_text": _normalize_text(node.get("manual_profile_text")),
        "corpus_source": corpus_source,
        "inventory_source": corpus_source,
        "original_index": original_index,
    }
    return route_doc


def _node_mapping_from_row(row: DocumentRoutingNode) -> dict[str, Any]:
    return {
        "node_id": row.node_id,
        "parent_node_id": row.parent_node_id,
        "title": row.title,
        "breadcrumb": row.breadcrumb,
        "depth": row.depth,
        "page_start": row.page_start,
        "page_end": row.page_end,
        "route_summary": row.route_summary,
        "contrastive_summary": row.contrastive_summary,
        "aliases_json": row.aliases_json,
        "keywords_json": row.keywords_json,
        "manual_profile_text": row.manual_profile_text,
    }


def _node_mapping_from_routing_payload(node: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node.get("node_id"),
        "parent_node_id": node.get("parent_node_id"),
        "title": node.get("title"),
        "breadcrumb": node.get("breadcrumb"),
        "depth": node.get("depth"),
        "page_start": node.get("page_start"),
        "page_end": node.get("page_end"),
        "route_summary": node.get("route_summary"),
        "contrastive_summary": node.get("contrastive_summary"),
        "aliases_json": node.get("aliases_json"),
        "keywords_json": node.get("keywords_json"),
        "manual_profile_text": node.get("manual_profile_text"),
    }


def _build_breadcrumb(manual_label: str | None, ancestors: Sequence[str]) -> str | None:
    parts: list[str] = []
    if _normalize_text(manual_label):
        parts.append(str(manual_label))
    parts.extend(part for part in ancestors if _normalize_text(part))
    if not parts:
        return None
    return " / ".join(parts)


def _collect_structure_node_mappings(
    nodes: list[dict[str, Any]] | dict[str, Any] | None,
    *,
    manual_label: str | None,
    parent_node_id: str | None = None,
    depth: int = 0,
    ancestors: list[str] | None = None,
    collected: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if collected is None:
        collected = []
    if not nodes:
        return collected

    node_items = nodes if isinstance(nodes, list) else [nodes]
    ancestor_titles = list(ancestors or [])
    for node in node_items:
        if not isinstance(node, Mapping):
            continue
        node_id = _normalize_text(node.get("node_id"))
        title = _normalize_text(node.get("title"))
        current_titles = ancestor_titles + ([title] if title else [])
        collected.append(
            {
                "node_id": node_id,
                "parent_node_id": parent_node_id,
                "title": title,
                "breadcrumb": _build_breadcrumb(manual_label, current_titles),
                "depth": depth,
                "page_start": node.get("start_index"),
                "page_end": node.get("end_index"),
                "route_summary": node.get("summary"),
                "contrastive_summary": None,
                "aliases_json": None,
                "keywords_json": None,
                "manual_profile_text": None,
            }
        )
        child_nodes = node.get("nodes") or []
        if child_nodes:
            _collect_structure_node_mappings(
                child_nodes,
                manual_label=manual_label,
                parent_node_id=node_id,
                depth=depth + 1,
                ancestors=current_titles,
                collected=collected,
            )
    return collected


def _route_docs_from_mappings(
    manual_ref: Mapping[str, Any],
    nodes: Sequence[Mapping[str, Any]],
    *,
    corpus_source: str,
) -> list[dict[str, Any]]:
    route_docs: list[dict[str, Any]] = []
    for index, node in enumerate(nodes):
        route_doc = _route_doc_from_node(
            manual_ref,
            node,
            corpus_source=corpus_source,
            original_index=index,
        )
        if route_doc is not None:
            route_docs.append(route_doc)
    return route_docs


def load_node_corpus_for_manual(
    manual_ref: Mapping[str, Any],
    *,
    routing_rows: Sequence[DocumentRoutingNode] | None = None,
) -> dict[str, Any]:
    """Load node shadow corpus without changing manual-gate inventory semantics."""

    manual_snapshot = dict(manual_ref)
    warning: str | None = None

    row_docs = _route_docs_from_mappings(
        manual_snapshot,
        [_node_mapping_from_row(row) for row in routing_rows or []],
        corpus_source="document_routing_nodes",
    )
    if row_docs:
        return {
            "manual_key": _manual_key(manual_snapshot),
            "manual": manual_snapshot,
            "corpus_source": "document_routing_nodes",
            "nodes": row_docs,
            "node_count": len(row_docs),
            "fallback_reason": None,
            "warning": None,
        }

    routing_index_path = _normalize_text(manual_snapshot.get("routing_index_path"))
    if routing_index_path:
        try:
            routing_payload = read_document_routing_index(routing_index_path)
            payload_nodes = routing_payload.get("nodes") if isinstance(routing_payload, Mapping) else None
            if isinstance(payload_nodes, list):
                index_docs = _route_docs_from_mappings(
                    manual_snapshot,
                    [
                        _node_mapping_from_routing_payload(node)
                        for node in payload_nodes
                        if isinstance(node, Mapping)
                    ],
                    corpus_source="routing_index_json",
                )
                if index_docs:
                    return {
                        "manual_key": _manual_key(manual_snapshot),
                        "manual": manual_snapshot,
                        "corpus_source": "routing_index_json",
                        "nodes": index_docs,
                        "node_count": len(index_docs),
                        "fallback_reason": "document_routing_nodes_missing",
                        "warning": None,
                    }
        except Exception as exc:  # pragma: no cover - defensive fallback
            warning = f"routing_index_json_unavailable:{type(exc).__name__}"

    parsed_structure_path = _normalize_text(manual_snapshot.get("parsed_structure_path"))
    if parsed_structure_path:
        try:
            structure = load_structure_file(parsed_structure_path)
            structure_nodes = _collect_structure_node_mappings(
                structure,
                manual_label=_normalize_text(manual_snapshot.get("document_label")),
            )
            structure_docs = _route_docs_from_mappings(
                manual_snapshot,
                structure_nodes,
                corpus_source="structure_json",
            )
            if structure_docs:
                return {
                    "manual_key": _manual_key(manual_snapshot),
                    "manual": manual_snapshot,
                    "corpus_source": "structure_json",
                    "nodes": structure_docs,
                    "node_count": len(structure_docs),
                    "fallback_reason": "routing_index_json_missing_or_unavailable",
                    "warning": warning,
                }
        except Exception as exc:  # pragma: no cover - defensive fallback
            warning = f"structure_json_unavailable:{type(exc).__name__}"

    return {
        "manual_key": _manual_key(manual_snapshot),
        "manual": manual_snapshot,
        "corpus_source": "metadata_only",
        "nodes": [],
        "node_count": 0,
        "fallback_reason": "node_corpus_unavailable",
        "warning": warning,
    }


def _rows_by_version_id(db: Session, version_ids: Sequence[str]) -> dict[str, list[DocumentRoutingNode]]:
    normalized_ids = [str(version_id) for version_id in version_ids if _normalize_text(version_id)]
    if not normalized_ids:
        return {}
    rows = db.scalars(
        select(DocumentRoutingNode)
        .where(DocumentRoutingNode.version_id.in_(normalized_ids))
        .order_by(DocumentRoutingNode.version_id.asc(), DocumentRoutingNode.depth.asc(), DocumentRoutingNode.node_id.asc())
    ).all()
    grouped: dict[str, list[DocumentRoutingNode]] = {}
    for row in rows:
        grouped.setdefault(row.version_id, []).append(row)
    return grouped


def build_node_corpora(db: Session, manual_refs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    version_ids = [
        str(manual_ref.get("version_id"))
        for manual_ref in manual_refs
        if _normalize_text(manual_ref.get("version_id")) is not None
    ]
    routing_rows = _rows_by_version_id(db, version_ids)
    return [
        load_node_corpus_for_manual(
            manual_ref,
            routing_rows=routing_rows.get(str(manual_ref.get("version_id") or "")) or [],
        )
        for manual_ref in manual_refs
    ]


def _text_hit_count(query_tokens: set[str], value: Any, *, cap: int) -> int:
    if not query_tokens:
        return 0
    candidate_tokens = set(tokenize_routing_text(_normalize_text(value)))
    if not candidate_tokens:
        return 0
    return min(len(query_tokens & candidate_tokens), cap)


def _substring_hit(query_tokens: Sequence[str], value: Any) -> bool:
    normalized = (_normalize_text(value) or "").lower()
    if not normalized:
        return False
    return any(token in normalized for token in query_tokens if len(token) >= 3)


def _stringify_optional_tokens(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(str(item) for pair in value.items() for item in pair if _normalize_text(item))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return " ".join(str(item) for item in value if _normalize_text(item))
    return str(value)


def _truncate_text(value: Any, max_chars: int = NODE_SECTION_TEXT_MAX_CHARS) -> str | None:
    text = _normalize_text(value)
    if text is None:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _bounded_cache_get(cache: OrderedDict[str, Any], key: str) -> Any:
    if key not in cache:
        return None
    value = cache.pop(key)
    cache[key] = value
    return value


def _bounded_cache_put(cache: OrderedDict[str, Any], key: str, value: Any, *, limit: int) -> None:
    if key in cache:
        cache.pop(key)
    cache[key] = value
    while len(cache) > limit:
        cache.popitem(last=False)


def _content_search_text(manual_ref: Mapping[str, Any], node: Mapping[str, Any]) -> str:
    parts = [
        node.get("title"),
        node.get("breadcrumb"),
        node.get("route_summary"),
        node.get("section_text"),
        _manual_metadata_text({**dict(manual_ref), **dict(node)}),
    ]
    return "\n".join(str(part) for part in parts if _normalize_text(part))


def _safe_section_text(
    manual_ref: Mapping[str, Any],
    node: Mapping[str, Any],
    *,
    page_cache: dict[str, list[tuple[str, int]] | None],
    es_section_texts: Mapping[str, Any],
    max_chars: int,
    allow_runtime_pdf_fallback: bool = False,
) -> tuple[str | None, str | None]:
    if _normalize_text(node.get("section_text")):
        return _truncate_text(node.get("section_text"), max_chars), "provided"

    node_key = _normalize_text(node.get("node_key"))
    node_id = _normalize_text(node.get("node_id"))
    es_record = es_section_texts.get(node_key or "") if node_key else None
    if es_record is None and node_id:
        es_record = es_section_texts.get(node_id)
    if bool(getattr(es_record, "stale", False)) or getattr(es_record, "status", None) == "stale":
        return None, "stale"
    es_text = getattr(es_record, "text", None) if es_record is not None else None
    if es_text:
        return _truncate_text(es_text, max_chars), "es_shadow"

    if not allow_runtime_pdf_fallback:
        return None, "missing"

    storage_path = _normalize_text(manual_ref.get("storage_path"))
    if not storage_path:
        return None, "storage_path_missing"
    page_start = _normalize_optional_int(node.get("page_start"))
    page_end = _normalize_optional_int(node.get("page_end"))
    if page_start is None or page_end is None or page_end < page_start:
        return None, "page_span_missing"

    if storage_path not in page_cache:
        cached_pages = _bounded_cache_get(_PAGE_TOKEN_CACHE, storage_path)
        if cached_pages is not None:
            page_cache[storage_path] = cached_pages
        else:
            try:
                with local_artifact_path(storage_path) as pdf_path:
                    page_cache[storage_path] = get_page_tokens(str(pdf_path), model=None)
                _bounded_cache_put(
                    _PAGE_TOKEN_CACHE,
                    storage_path,
                    page_cache[storage_path],
                    limit=NODE_PAGE_TOKEN_CACHE_LIMIT,
                )
            except Exception as exc:  # pragma: no cover - defensive artifact fallback
                page_cache[storage_path] = None
                _bounded_cache_put(
                    _PAGE_TOKEN_CACHE,
                    storage_path,
                    None,
                    limit=NODE_PAGE_TOKEN_CACHE_LIMIT,
                )
                return None, f"pdf_text_unavailable:{type(exc).__name__}"

    pages = page_cache.get(storage_path)
    if not pages:
        return None, "pdf_text_unavailable"
    bounded_start = max(1, page_start)
    bounded_end = min(len(pages), page_end)
    if bounded_end < bounded_start:
        return None, "page_span_out_of_range"
    try:
        section_text = get_text_of_pdf_pages_with_labels(pages, bounded_start, bounded_end)
    except Exception as exc:  # pragma: no cover - defensive page fallback
        return None, f"pdf_text_unavailable:{type(exc).__name__}"
    return _truncate_text(section_text, max_chars), "pdf_pages"


def enrich_node_corpora_with_content(
    node_corpora: Sequence[Mapping[str, Any]],
    *,
    max_section_chars: int = NODE_SECTION_TEXT_MAX_CHARS,
    section_text_provider: SectionTextProvider | None = None,
    embedding_config: Mapping[str, Any] | None = None,
    settings_obj: Any | None = None,
    allow_runtime_pdf_fallback: bool = False,
) -> list[dict[str, Any]]:
    provider = section_text_provider or SectionTextProvider(
        embedding_config=embedding_config,
        settings_obj=settings_obj,
    )
    page_cache: dict[str, list[tuple[str, int]] | None] = {}
    enriched_corpora: list[dict[str, Any]] = []
    for corpus in node_corpora:
        manual = dict(corpus.get("manual") or {})
        es_batch = provider.get_for_nodes(
            manual,
            [node for node in corpus.get("nodes") or [] if isinstance(node, Mapping)],
        )
        enriched_nodes: list[dict[str, Any]] = []
        for node in corpus.get("nodes") or []:
            if not isinstance(node, Mapping):
                continue
            enriched = dict(node)
            section_text, source = _safe_section_text(
                manual,
                enriched,
                page_cache=page_cache,
                es_section_texts=es_batch.records,
                max_chars=max_section_chars,
                allow_runtime_pdf_fallback=allow_runtime_pdf_fallback,
            )
            if section_text:
                enriched["section_text"] = section_text
                enriched["section_text_source"] = source
                enriched["section_text_available"] = True
            else:
                enriched["section_text_source"] = source
                enriched["section_text_available"] = False
            enriched["searchable_text"] = _content_search_text(manual, enriched)
            enriched_nodes.append(enriched)
        next_corpus = dict(corpus)
        next_corpus["nodes"] = enriched_nodes
        next_corpus["content_summary"] = {
            "node_count": len(enriched_nodes),
            "section_text_node_count": sum(1 for node in enriched_nodes if node.get("section_text_available")),
            "es_section_text_count": sum(1 for node in enriched_nodes if node.get("section_text_source") == "es_shadow"),
            "section_text_source": es_batch.source,
            "section_text_status": es_batch.status,
            "section_text_degraded_reason": es_batch.degraded_reason,
            "section_text_index_name": es_batch.index_name,
            "runtime_pdf_fallback_allowed": bool(allow_runtime_pdf_fallback),
            "storage_paths_loaded": sum(1 for pages in page_cache.values() if pages),
        }
        enriched_corpora.append(next_corpus)
    return enriched_corpora


def _compact_for_phrase(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").lower())


def _query_phrases(question: str | None) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    for phrase in _CJK_PHRASE_RE.findall(str(question or "").lower()):
        compact = _compact_for_phrase(phrase)
        if compact and compact not in seen:
            phrases.append(compact)
            seen.add(compact)
    return phrases


def _body_phrase_hits(question: str | None, body_text: Any) -> list[str]:
    compact_body = _compact_for_phrase(body_text)
    if not compact_body:
        return []
    return [phrase for phrase in _query_phrases(question) if phrase in compact_body]


def _lexical_raw_score(question: str, query_tokens_list: Sequence[str], node: Mapping[str, Any]) -> tuple[float, dict[str, Any]]:
    query_tokens = set(query_tokens_list)
    title_hits = _text_hit_count(query_tokens, node.get("title"), cap=8)
    breadcrumb_hits = _text_hit_count(query_tokens, node.get("breadcrumb"), cap=8)
    manual_hits = _text_hit_count(query_tokens, _manual_metadata_text(node), cap=6)
    summary_hits = _text_hit_count(query_tokens, node.get("route_summary"), cap=6)
    section_text = node.get("section_text")
    section_hits = _text_hit_count(query_tokens, section_text, cap=40)
    section_phrase_hits = _body_phrase_hits(question, section_text)
    optional_hits = _text_hit_count(
        query_tokens,
        " ".join(
            [
                _stringify_optional_tokens(node.get("aliases")),
                _stringify_optional_tokens(node.get("keywords")),
                _normalize_text(node.get("manual_profile_text")) or "",
                _normalize_text(node.get("contrastive_summary")) or "",
                _normalize_text(node.get("searchable_text")) or "",
            ]
        ),
        cap=4,
    )
    title_phrase_hit = _substring_hit(query_tokens_list, node.get("title"))
    breadcrumb_phrase_hit = _substring_hit(query_tokens_list, node.get("breadcrumb"))
    summary_phrase_hit = _substring_hit(query_tokens_list, node.get("route_summary"))
    section_phrase_hit = bool(section_phrase_hits) or _substring_hit(query_tokens_list, section_text)
    has_text_hit = bool(title_hits or breadcrumb_hits or manual_hits or summary_hits or optional_hits or section_hits or section_phrase_hit)

    page_span = _normalize_optional_int(node.get("page_span"))
    if has_text_hit and page_span is not None and page_span <= 2:
        span_bonus = 0.7
    elif has_text_hit and page_span is not None and page_span <= 5:
        span_bonus = 0.4
    elif has_text_hit and page_span is not None and page_span <= 10:
        span_bonus = 0.2
    else:
        span_bonus = 0.0
    depth_bonus = 0.12 * min(_normalize_optional_int(node.get("depth")) or 0, 4) if has_text_hit else 0.0

    raw_score = (
        title_hits * 4.0
        + (3.0 if title_phrase_hit else 0.0)
        + breadcrumb_hits * 2.0
        + (1.0 if breadcrumb_phrase_hit else 0.0)
        + manual_hits * 1.25
        + summary_hits * 0.75
        + (0.5 if summary_phrase_hit else 0.0)
        + section_hits * 3.0
        + (18.0 if section_phrase_hits else 0.0)
        + (6.0 if section_phrase_hit and not section_phrase_hits else 0.0)
        + optional_hits * 0.35
        + span_bonus
        + depth_bonus
    )
    features = {
        "title_hit_count": title_hits,
        "breadcrumb_hit_count": breadcrumb_hits,
        "manual_metadata_hit_count": manual_hits,
        "route_summary_hit_count": summary_hits,
        "section_text_hit_count": section_hits,
        "optional_field_hit_count": optional_hits,
        "title_phrase_hit": title_phrase_hit,
        "breadcrumb_phrase_hit": breadcrumb_phrase_hit,
        "route_summary_phrase_hit": summary_phrase_hit,
        "section_text_phrase_hit": section_phrase_hit,
        "section_text_exact_phrase_hits": section_phrase_hits,
        "section_text_available": bool(node.get("section_text_available") or _normalize_text(section_text)),
        "page_span_bonus": span_bonus,
        "depth_bonus": round(depth_bonus, 4),
    }
    return round(raw_score, 6), features


def _source_rank(corpus_source: Any) -> int:
    try:
        return NODE_CORPUS_SOURCE_PRIORITY.index(str(corpus_source or "metadata_only"))
    except ValueError:
        return len(NODE_CORPUS_SOURCE_PRIORITY)


def _sort_nodes(nodes: Sequence[Mapping[str, Any]], score_key: str) -> list[dict[str, Any]]:
    return sorted(
        (dict(node) for node in nodes),
        key=lambda item: (
            -float(item.get(score_key) or 0.0),
            -float(item.get("lexical_score") or 0.0),
            _source_rank(item.get("corpus_source")),
            int(item.get("manual_original_index") or 0),
            int(item.get("original_index") or 0),
            str(item.get("node_id") or ""),
        ),
    )


def _dense_score_for(node: Mapping[str, Any], dense_scores: Mapping[Any, Any] | None) -> float | None:
    if not dense_scores:
        return None
    candidates: list[Any] = [
        node.get("node_key"),
        f"{node.get('manual_key')}:{node.get('node_id')}",
        node.get("node_id"),
        (node.get("document_id"), node.get("version_id"), node.get("node_id")),
    ]
    for key in candidates:
        if key in dense_scores:
            return _normalize_float(dense_scores.get(key))
    return None


def _normalized_embedding_build_mode(value: Any) -> str:
    normalized = str(value or "disabled").strip().lower().replace("-", "_")
    if normalized in {"1", "true", "yes", "on", "enable", "enabled", "build"}:
        return "enabled"
    if normalized in {"dryrun", "dry_run", "dry"}:
        return "dry_run"
    return "disabled"


def resolve_dense_shadow_state(
    *,
    embedding_mode: str | None = None,
    provider_config: Mapping[str, Any] | None = None,
    embedding_config: Mapping[str, Any] | None = None,
    dense_scores: Mapping[Any, Any] | None = None,
    settings_obj: Any | None = None,
) -> dict[str, Any]:
    raw_mode = _normalize_text(embedding_mode)
    normalized_mode = raw_mode.lower() if raw_mode else "off"
    if normalized_mode in {"disabled", "disable", "false", "0", "no"}:
        normalized_mode = "off"
    if normalized_mode not in {"auto", "off", "provider", "system"}:
        return {
            "enabled": False,
            "requested_mode": normalized_mode,
            "resolved_mode": "off",
            "fallback_reason": "invalid_embedding_mode_disabled",
            "dense_cache_present": bool(dense_scores),
        }
    if normalized_mode == "off":
        return {
            "enabled": False,
            "requested_mode": normalized_mode,
            "resolved_mode": "off",
            "fallback_reason": "embedding_mode_disabled",
            "dense_cache_present": bool(dense_scores),
        }

    settings = settings_obj or get_settings()
    build_mode = _normalized_embedding_build_mode(getattr(settings, "routing_embeddings_build_mode", "disabled"))
    if build_mode == "disabled" and not dense_scores:
        return {
            "enabled": False,
            "requested_mode": normalized_mode,
            "resolved_mode": "sparse_only",
            "fallback_reason": "embedding_build_mode_disabled",
            "dense_cache_present": bool(dense_scores),
        }

    resolved_config = dict(
        embedding_config
        or resolve_embedding_config(
            provider_config=dict(provider_config or {}),
            embedding_mode=normalized_mode,
        )
    )
    if not resolved_config.get("enabled"):
        fallback_reason = _normalize_text(resolved_config.get("fallback_reason")) or "embedding_unavailable"
        return {
            "enabled": False,
            "requested_mode": normalized_mode,
            "resolved_mode": _normalize_text(resolved_config.get("resolved_mode")) or "sparse_only",
            "fallback_reason": f"embedding_unavailable:{fallback_reason}",
            "dense_cache_present": bool(dense_scores),
        }
    if not dense_scores:
        return {
            "enabled": False,
            "requested_mode": normalized_mode,
            "resolved_mode": "sparse_only",
            "provider_source": _normalize_text(resolved_config.get("provider_source")),
            "provider_type": _normalize_text(resolved_config.get("provider_type")),
            "model": _normalize_text(resolved_config.get("model")),
            "fallback_reason": "embedding_cache_missing",
            "dense_cache_present": False,
        }
    return {
        "enabled": True,
        "requested_mode": normalized_mode,
        "resolved_mode": "hybrid",
        "provider_source": _normalize_text(resolved_config.get("provider_source")),
        "provider_type": _normalize_text(resolved_config.get("provider_type")),
        "model": _normalize_text(resolved_config.get("model")),
        "fallback_reason": None,
        "dense_cache_present": True,
    }


def score_node_corpora(
    question: str,
    node_corpora: Sequence[Mapping[str, Any]],
    *,
    top_k: int = 8,
    candidate_top_k: int | None = None,
    embedding_mode: str | None = None,
    provider_config: Mapping[str, Any] | None = None,
    embedding_config: Mapping[str, Any] | None = None,
    dense_scores: Mapping[Any, Any] | None = None,
    dense_search_metadata: Mapping[str, Any] | None = None,
    settings_obj: Any | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    resolved_top_k = max(0, int(top_k or 0))
    resolved_candidate_top_k = max(resolved_top_k, int(candidate_top_k or resolved_top_k or 0))
    query_tokens = tokenize_routing_text(question)
    scored_nodes: list[dict[str, Any]] = []

    for manual_index, corpus in enumerate(node_corpora):
        for node in corpus.get("nodes") or []:
            if not isinstance(node, Mapping):
                continue
            raw_score, features = _lexical_raw_score(question, query_tokens, node)
            scored = dict(node)
            scored["manual_original_index"] = manual_index
            scored["lexical_raw_score"] = raw_score
            scored["lexical_features"] = features
            scored["zero_hit"] = raw_score <= 0
            scored_nodes.append(scored)

    max_raw_score = max((float(node.get("lexical_raw_score") or 0.0) for node in scored_nodes), default=0.0)
    for node in scored_nodes:
        if max_raw_score > 0:
            node["lexical_score"] = round(float(node.get("lexical_raw_score") or 0.0) / max_raw_score, 6)
        else:
            node["lexical_score"] = 0.0

    dense_state = resolve_dense_shadow_state(
        embedding_mode=embedding_mode,
        provider_config=provider_config,
        embedding_config=embedding_config,
        dense_scores=dense_scores,
        settings_obj=settings_obj,
    )
    if dense_search_metadata:
        dense_state["dense_source"] = dense_search_metadata.get("dense_source")
        dense_state["requested_dense_source"] = dense_search_metadata.get("requested_dense_source")
        dense_state["query_embedding_dimensions"] = dense_search_metadata.get("query_embedding_dimensions")
        dense_state["artifact_count"] = dense_search_metadata.get("artifact_count")
        dense_state["artifacts"] = list(dense_search_metadata.get("artifacts") or [])
        dense_state["es"] = dict(dense_search_metadata.get("es") or {})
        if dense_search_metadata.get("fallback_reason"):
            dense_state["fallback_reason"] = dense_search_metadata.get("fallback_reason")
    elif dense_scores:
        dense_state["dense_source"] = "injected_dense_scores"
    dense_cache_miss_count = 0
    for node in scored_nodes:
        dense_score = _dense_score_for(node, dense_scores) if dense_state.get("enabled") else None
        if dense_state.get("enabled") and dense_score is None:
            dense_cache_miss_count += 1
            dense_score = 0.0
        node["dense_score"] = dense_score
        if dense_state.get("enabled"):
            node["hybrid_score"] = round(
                (NODE_LEXICAL_WEIGHT * float(node.get("lexical_score") or 0.0))
                + (NODE_DENSE_WEIGHT * float(dense_score or 0.0)),
                6,
            )
            node["hybrid_mode"] = "hybrid"
        else:
            node["hybrid_score"] = node["lexical_score"]
            node["hybrid_mode"] = "sparse_only"

    lexical_ranked = _sort_nodes(scored_nodes, "lexical_score")
    hybrid_ranked = _sort_nodes(scored_nodes, "hybrid_score")
    for rank, node in enumerate(lexical_ranked, start=1):
        node["lexical_rank"] = rank
    lexical_rank_by_key = {node.get("node_key"): node.get("lexical_rank") for node in lexical_ranked}
    for rank, node in enumerate(hybrid_ranked, start=1):
        node["hybrid_rank"] = rank
        node["lexical_rank"] = lexical_rank_by_key.get(node.get("node_key"))

    manual_zero_hit_count = 0
    manual_count_with_corpus = 0
    section_text_node_count = 0
    source_counts: Counter[str] = Counter()
    for corpus in node_corpora:
        source = str(corpus.get("corpus_source") or NODE_CORPUS_METADATA_ONLY_SOURCE)
        source_counts[source] += 1
        content_summary = corpus.get("content_summary") if isinstance(corpus.get("content_summary"), Mapping) else {}
        section_text_node_count += int(content_summary.get("section_text_node_count") or 0)
        nodes = [
            node
            for node in scored_nodes
            if node.get("manual_key") == corpus.get("manual_key")
        ]
        if nodes:
            manual_count_with_corpus += 1
            if all(bool(node.get("zero_hit")) for node in nodes):
                manual_zero_hit_count += 1

    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "score_version": NODE_SHADOW_SCORE_VERSION,
        "question": question,
        "query_tokens": query_tokens,
        "top_k": resolved_top_k,
        "candidate_top_k": resolved_candidate_top_k,
        "dense": {
            **dense_state,
            "dense_cache_miss_count": dense_cache_miss_count,
            "lexical_weight": NODE_LEXICAL_WEIGHT,
            "dense_weight": NODE_DENSE_WEIGHT,
        },
        "corpus_summary": {
            "manual_count": len(node_corpora),
            "manual_count_with_corpus": manual_count_with_corpus,
            "node_count": len(scored_nodes),
            "section_text_node_count": section_text_node_count,
            "source_counts": {key: int(value) for key, value in source_counts.items()},
            "metadata_only_manual_count": int(source_counts.get(NODE_CORPUS_METADATA_ONLY_SOURCE, 0)),
            "manual_zero_hit_count": manual_zero_hit_count,
        },
        "node_shadow_latency_ms": latency_ms,
        "lexical_top_nodes": lexical_ranked[:resolved_candidate_top_k],
        "hybrid_top_nodes": hybrid_ranked[:resolved_candidate_top_k],
        "shortlist": hybrid_ranked[:resolved_top_k],
        "node_corpora": [dict(corpus) for corpus in node_corpora],
    }


def _node_identity(item: Mapping[str, Any]) -> tuple[str, str, str] | None:
    document_id = _normalize_text(item.get("document_id"))
    version_id = _normalize_text(item.get("version_id"))
    node_id = _normalize_text(item.get("node_id"))
    if not document_id or not version_id or not node_id:
        return None
    return document_id, version_id, node_id


def _outline_identities(outline_diagnostics: Mapping[str, Any] | None) -> set[tuple[str, str, str]]:
    if not isinstance(outline_diagnostics, Mapping):
        return set()
    identities: set[tuple[str, str, str]] = set()
    manuals = outline_diagnostics.get("manuals")
    if not isinstance(manuals, list):
        return identities
    for manual in manuals:
        if not isinstance(manual, Mapping):
            continue
        document_id = _normalize_text(manual.get("document_id"))
        version_id = _normalize_text(manual.get("version_id"))
        if not document_id or not version_id:
            continue
        for node_id in manual.get("selected_node_ids") or []:
            normalized_node_id = _normalize_text(node_id)
            if normalized_node_id:
                identities.add((document_id, version_id, normalized_node_id))
    return identities


def _citation_identities(citations: Sequence[Mapping[str, Any]] | None) -> set[tuple[str, str, str]]:
    identities: set[tuple[str, str, str]] = set()
    for citation in citations or []:
        if not isinstance(citation, Mapping):
            continue
        identity = _node_identity(citation)
        if identity is not None:
            identities.add(identity)
    return identities


def _top_node_identities(nodes: Sequence[Mapping[str, Any]], top_k: int) -> set[tuple[str, str, str]]:
    identities: set[tuple[str, str, str]] = set()
    for node in list(nodes)[: max(0, top_k)]:
        identity = _node_identity(node)
        if identity is not None:
            identities.add(identity)
    return identities


def _recall(selected: set[tuple[str, str, str]], reference: set[tuple[str, str, str]]) -> dict[str, Any]:
    matched = selected & reference
    return {
        "value": _rate(len(matched), len(reference)),
        "matched_count": len(matched),
        "reference_count": len(reference),
        "matched_node_ids": sorted(":".join(identity) for identity in matched),
    }


def evaluate_node_shadow_metrics(
    score_result: Mapping[str, Any],
    *,
    outline_diagnostics: Mapping[str, Any] | None = None,
    final_citations: Sequence[Mapping[str, Any]] | None = None,
    retrieve_candidates_latency_ms: int | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    resolved_top_k = int(top_k or score_result.get("top_k") or 0)
    lexical_nodes = list(score_result.get("lexical_top_nodes") or [])
    hybrid_nodes = list(score_result.get("hybrid_top_nodes") or [])

    outline_reference = _outline_identities(outline_diagnostics)
    citation_reference = _citation_identities(final_citations)
    lexical_top = _top_node_identities(lexical_nodes, resolved_top_k)
    hybrid_top = _top_node_identities(hybrid_nodes, resolved_top_k)

    lexical_outline = _recall(lexical_top, outline_reference)
    hybrid_outline = _recall(hybrid_top, outline_reference)
    lexical_citation = _recall(lexical_top, citation_reference)
    hybrid_citation = _recall(hybrid_top, citation_reference)

    dense = dict(score_result.get("dense") or {})
    if dense.get("enabled"):
        hybrid_vs_lexical_gain: dict[str, Any] = {
            "value": round(float(hybrid_citation["value"]) - float(lexical_citation["value"]), 6),
            "outline_overlap_delta": round(float(hybrid_outline["value"]) - float(lexical_outline["value"]), 6),
            "final_citation_recall_delta": round(float(hybrid_citation["value"]) - float(lexical_citation["value"]), 6),
            "skipped_reason": None,
        }
    else:
        hybrid_vs_lexical_gain = {
            "value": None,
            "outline_overlap_delta": None,
            "final_citation_recall_delta": None,
            "skipped_reason": dense.get("fallback_reason") or "dense_not_enabled",
        }

    corpus_summary = dict(score_result.get("corpus_summary") or {})
    manual_count = int(corpus_summary.get("manual_count") or 0)
    manual_count_with_corpus = int(corpus_summary.get("manual_count_with_corpus") or 0)
    manual_zero_hit_count = int(corpus_summary.get("manual_zero_hit_count") or 0)
    source_counts = dict(corpus_summary.get("source_counts") or {})
    fallback_sources = {
        source: int(source_counts.get(source, 0))
        for source in NODE_CORPUS_SOURCE_PRIORITY
        if source != NODE_CORPUS_PRIMARY_SOURCE and int(source_counts.get(source, 0))
    }
    fallback_needed_count = sum(fallback_sources.values())
    node_shadow_latency_ms = int(score_result.get("node_shadow_latency_ms") or 0)
    latency_delta = None
    if retrieve_candidates_latency_ms is not None:
        latency_delta = node_shadow_latency_ms - int(retrieve_candidates_latency_ms)

    return {
        "top_k": resolved_top_k,
        "node_topk_overlap_with_outline": {
            **hybrid_outline,
            "lexical_value": lexical_outline["value"],
            "hybrid_value": hybrid_outline["value"],
            "outline_node_count": len(outline_reference),
        },
        "node_topk_recall_of_final_citation_nodes": {
            **hybrid_citation,
            "lexical_value": lexical_citation["value"],
            "hybrid_value": hybrid_citation["value"],
            "final_citation_node_count": len(citation_reference),
        },
        "hybrid_vs_lexical_gain": hybrid_vs_lexical_gain,
        "latency_delta": {
            "node_shadow_latency_ms": node_shadow_latency_ms,
            "retrieve_candidates_latency_ms": retrieve_candidates_latency_ms,
            "delta_ms": latency_delta,
        },
        "zero_hit_rate": {
            "value": _rate(manual_zero_hit_count, manual_count_with_corpus),
            "zero_hit_manual_count": manual_zero_hit_count,
            "manual_count_with_corpus": manual_count_with_corpus,
        },
        "fallback_needed_rate": {
            "value": _rate(fallback_needed_count, manual_count),
            "fallback_needed_count": fallback_needed_count,
            "manual_count": manual_count,
            "by_source": fallback_sources,
        },
    }


def normalize_node_shadow_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    manual_gate_result = payload.get("manual_gate_result")
    manuals: Any = payload.get("manuals") or payload.get("top_manuals")
    if manuals is None and isinstance(manual_gate_result, Mapping):
        manuals = manual_gate_result.get("applied_manuals")
    if manuals is None and isinstance(payload.get("manual_gate"), Mapping):
        manuals = payload["manual_gate"].get("applied_manuals")
    manuals = list(manuals or [])

    question = _normalize_text(payload.get("retrieval_query")) or _normalize_text(payload.get("question")) or ""
    top_k = max(1, int(payload.get("top_k") or 8))
    candidate_top_k = max(top_k, int(payload.get("candidate_top_k") or top_k))
    return {
        "question": question,
        "retrieval_query": question,
        "run_kind": _normalize_text(payload.get("run_kind")) or "offline",
        "run_id": _normalize_text(payload.get("run_id")),
        "top_k": top_k,
        "candidate_top_k": candidate_top_k,
        "manuals": [dict(manual) for manual in manuals if isinstance(manual, Mapping)],
        "outline_diagnostics": payload.get("outline_diagnostics") or payload.get("outline"),
        "final_citations": list(payload.get("final_citations") or payload.get("citations") or []),
        "retrieve_candidates_latency_ms": payload.get("retrieve_candidates_latency_ms"),
        "embedding_mode": _normalize_text(payload.get("embedding_mode")),
    }


def build_node_shadow_report(
    normalized_input: Mapping[str, Any],
    score_result: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": NODE_SHADOW_REPORT_SCHEMA_VERSION,
        "score_version": NODE_SHADOW_SCORE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input": {
            "run_kind": normalized_input.get("run_kind"),
            "run_id": normalized_input.get("run_id"),
            "retrieval_query": normalized_input.get("retrieval_query") or normalized_input.get("question"),
            "top_k": normalized_input.get("top_k"),
            "candidate_top_k": normalized_input.get("candidate_top_k"),
            "manual_count": len(normalized_input.get("manuals") or []),
        },
        "dense": dict(score_result.get("dense") or {}),
        "corpus_summary": dict(score_result.get("corpus_summary") or {}),
        "metrics": dict(metrics),
        "shortlist": list(score_result.get("shortlist") or []),
        "lexical_top_nodes": list(score_result.get("lexical_top_nodes") or []),
        "hybrid_top_nodes": list(score_result.get("hybrid_top_nodes") or []),
    }


def run_node_shadow_replay(
    db: Session,
    payload: Mapping[str, Any],
    *,
    provider_config: Mapping[str, Any] | None = None,
    embedding_config: Mapping[str, Any] | None = None,
    dense_scores: Mapping[Any, Any] | None = None,
    dense_search_backend: NodeDenseSearchBackend | None = None,
    node_corpora: Sequence[Mapping[str, Any]] | None = None,
    settings_obj: Any | None = None,
) -> dict[str, Any]:
    normalized = normalize_node_shadow_input(payload)
    corpora = list(node_corpora) if node_corpora is not None else build_node_corpora(db, normalized["manuals"])
    dense_search_metadata: Mapping[str, Any] | None = None
    if dense_scores is None and dense_search_backend is not None:
        dense_result = dense_search_backend.search(
            query=normalized["retrieval_query"],
            node_corpora=corpora,
            embedding_mode=normalized.get("embedding_mode"),
            provider_config=provider_config,
            embedding_config=embedding_config,
            settings_obj=settings_obj,
        )
        dense_scores = dense_result.dense_scores or None
        dense_search_metadata = dense_result.metadata()
    score_result = score_node_corpora(
        normalized["retrieval_query"],
        corpora,
        top_k=normalized["top_k"],
        candidate_top_k=normalized["candidate_top_k"],
        embedding_mode=normalized.get("embedding_mode"),
        provider_config=provider_config,
        embedding_config=embedding_config,
        dense_scores=dense_scores,
        dense_search_metadata=dense_search_metadata,
        settings_obj=settings_obj,
    )
    latency = normalized.get("retrieve_candidates_latency_ms")
    try:
        retrieve_latency_ms = int(latency) if latency is not None else None
    except (TypeError, ValueError):
        retrieve_latency_ms = None
    metrics = evaluate_node_shadow_metrics(
        score_result,
        outline_diagnostics=normalized.get("outline_diagnostics"),
        final_citations=normalized.get("final_citations"),
        retrieve_candidates_latency_ms=retrieve_latency_ms,
        top_k=normalized["top_k"],
    )
    return build_node_shadow_report(normalized, score_result, metrics)


__all__ = [
    "NODE_CORPUS_SOURCE_PRIORITY",
    "NODE_SHADOW_REPORT_SCHEMA_VERSION",
    "NODE_SHADOW_SCORE_VERSION",
    "build_node_corpora",
    "build_node_shadow_report",
    "enrich_node_corpora_with_content",
    "evaluate_node_shadow_metrics",
    "load_node_corpus_for_manual",
    "normalize_node_shadow_input",
    "resolve_dense_shadow_state",
    "run_node_shadow_replay",
    "score_node_corpora",
    "run_fast_search",
    "COMPLEX_QUERY_PATTERN",
]

COMPLEX_QUERY_PATTERN = re.compile(r"(能否|是否|所有|完整|合规|多条件|雨夜|低能见|怎么)")

def run_fast_search(
    db,
    principal,
    document,
    version,
    query: str,
    top_k: int = 10,
    include_snippets: bool = True,
    dense_search_backend = None,
    settings_obj = None,
    allow_runtime_pdf_fallback: bool = False,
) -> dict:
    from app.services.routing_consumer_service import build_manual_gate_ref
    started = time.perf_counter()

    # 1. Complex Query Detection
    is_complex = bool(COMPLEX_QUERY_PATTERN.search(query))
    fallback_recommendation = "建议使用 DeepResearch" if is_complex else None
    boundary_flags = ["complex_query"] if is_complex else []

    # 2. Build Manual Ref
    manual_ref = build_manual_gate_ref(
        document_id=document.id,
        version_id=version.id,
        document_label=document.display_name,
        version_label=f"v{version.version_no}",
        display_name=document.display_name,
        source_filename=document.source_filename,
        storage_path=version.storage_path,
        parsed_structure_path=version.parsed_structure_path,
        routing_index_status=version.routing_index_status,
        routing_index_path=version.routing_index_path,
        routing_index_version=version.routing_index_version,
    )
    manual_ref["tenant_id"] = document.tenant_id

    # 3. Build Node Corpora
    step_started = time.perf_counter()
    raw_corpora = build_node_corpora(db, [manual_ref])
    corpus_load_latency_ms = int((time.perf_counter() - step_started) * 1000)
    step_started = time.perf_counter()
    corpora = enrich_node_corpora_with_content(
        raw_corpora,
        settings_obj=settings_obj,
        allow_runtime_pdf_fallback=allow_runtime_pdf_fallback,
    )
    content_enrich_latency_ms = int((time.perf_counter() - step_started) * 1000)

    # 4. Dense Search
    dense_scores = None
    dense_search_metadata = None
    dense_search_latency_ms = 0
    if dense_search_backend is not None:
        step_started = time.perf_counter()
        try:
            dense_result = dense_search_backend.search(
                query=query,
                node_corpora=corpora,
                embedding_mode="system",
                provider_config=None,
                embedding_config=None,
                settings_obj=settings_obj,
            )
            dense_scores = dense_result.dense_scores or None
            dense_search_metadata = dense_result.metadata()
        except Exception as e:
            dense_search_metadata = {"fallback_reason": f"dense_search_error: {str(e)}"}
        dense_search_latency_ms = int((time.perf_counter() - step_started) * 1000)

    # 5. Score Nodes
    step_started = time.perf_counter()
    score_result = score_node_corpora(
        question=query,
        node_corpora=corpora,
        top_k=top_k,
        candidate_top_k=top_k * 2,
        embedding_mode="system",
        dense_scores=dense_scores,
        dense_search_metadata=dense_search_metadata,
        settings_obj=settings_obj,
    )
    node_score_latency_ms = int((time.perf_counter() - step_started) * 1000)

    # 6. Format Response
    nodes = []
    mode = score_result.get("dense", {}).get("resolved_mode", "sparse_only")
    for item in score_result.get("shortlist", []):
        snippet = (
            _truncate_text(item.get("section_text"), 1200)
            or item.get("route_summary")
            if include_snippets
            else None
        )
        nodes.append({
            "node_id": item.get("node_id"),
            "title": item.get("title"),
            "page_start": item.get("page_start"),
            "page_end": item.get("page_end"),
            "score": item.get("hybrid_score", 0.0),
            "source": item.get("corpus_source", "unknown"),
            "snippet": snippet,
            "summary": item.get("route_summary"),
        })

    fallback_reason = score_result.get("dense", {}).get("fallback_reason")
    if fallback_reason and not is_complex:
        fallback_recommendation = f"Fallback to lexical search: {fallback_reason}"

    dense_info = score_result.get("dense", {})
    corpus_summary = score_result.get("corpus_summary", {})
    section_text_node_count = int(corpus_summary.get("section_text_node_count") or 0)
    content_summaries = [
        dict(corpus.get("content_summary") or {})
        for corpus in corpora
        if isinstance(corpus, Mapping)
    ]
    section_text_sources = sorted(
        {
            str(summary.get("section_text_source"))
            for summary in content_summaries
            if summary.get("section_text_source")
        }
    )
    section_text_degraded_reasons = sorted(
        {
            str(summary.get("section_text_degraded_reason"))
            for summary in content_summaries
            if summary.get("section_text_degraded_reason")
        }
    )
    if section_text_node_count <= 0 and not is_complex:
        fallback_recommendation = "FastSearch data not ready; use DeepResearch or rebuild fast index"
    es_metadata = dense_info.get("es") if isinstance(dense_info.get("es"), Mapping) else {}
    active_backend = "lexical_fallback"
    if mode == "hybrid":
        if dense_info.get("es", {}).get("used") or dense_info.get("dense_source") == "es_shadow":
            active_backend = "es_shadow"
        elif dense_info.get("dense_source") == "artifact_exact_scan":
            active_backend = "lexical_fallback"
        else:
            active_backend = dense_info.get("dense_source", "lexical_fallback")
    total_latency_ms = int((time.perf_counter() - started) * 1000)

    return {
        "mode": mode,
        "node_top_k": top_k,
        "latency_ms": total_latency_ms,
        "server_total_latency_ms": total_latency_ms,
        "corpus_load_latency_ms": corpus_load_latency_ms,
        "content_enrich_latency_ms": content_enrich_latency_ms,
        "dense_search_latency_ms": dense_search_latency_ms,
        "node_score_latency_ms": node_score_latency_ms,
        "legacy_node_shadow_latency_ms": score_result.get("node_shadow_latency_ms", 0),
        "nodes": nodes,
        "boundary_flags": boundary_flags,
        "fallback_recommendation": fallback_recommendation,
        "active_backend": active_backend,
        "fallback_reason": fallback_reason,
        "requested_dense_source": dense_info.get("requested_dense_source"),
        "dense_source": dense_info.get("dense_source"),
        "query_embedding_computed": bool(dense_info.get("query_embedding_dimensions")),
        "query_embedding_dimensions": dense_info.get("query_embedding_dimensions"),
        "artifact_count": dense_info.get("artifact_count"),
        "artifact_exact_scan_executed": False,
        "es_executed": bool(es_metadata.get("searched_indices") or es_metadata.get("used")),
        "section_text_participated": section_text_node_count > 0,
        "section_text_node_count": section_text_node_count,
        "section_text_source": ",".join(section_text_sources) if section_text_sources else "missing",
        "section_text_degraded_reason": ",".join(section_text_degraded_reasons) if section_text_degraded_reasons else None,
        "runtime_pdf_fallback_allowed": bool(allow_runtime_pdf_fallback),
    }
