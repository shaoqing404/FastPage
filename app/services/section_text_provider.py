from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.core.config import get_settings
from app.services.node_embedding_service import (
    DEFAULT_NODE_ES_INDEX_PREFIX,
    EsNodeDenseSearchBackend,
    embedding_spec_id_for_config,
    es_index_name_for_embedding_bundle,
)
from app.services.provider_service import resolve_embedding_config


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _expected_checksum(values: Sequence[Mapping[str, Any]]) -> tuple[str | None, str | None]:
    for value in values:
        if not isinstance(value, Mapping):
            continue
        checksum = _normalize_text(value.get("section_text_checksum"))
        if checksum:
            return checksum, "section_text_checksum_mismatch"
        checksum = _normalize_text(value.get("routing_node_checksum"))
        if checksum:
            return checksum, "routing_node_checksum_mismatch"
    return None, None


@dataclass
class SectionTextResult:
    text: str | None
    source: str
    status: str
    checksum: str | None = None
    stale: bool = False
    degraded_reason: str | None = None
    node_id: str | None = None
    node_key: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    title: str | None = None


@dataclass
class SectionTextBatch:
    records: dict[str, SectionTextResult]
    source: str
    status: str
    degraded_reason: str | None = None
    index_name: str | None = None
    hit_count: int = 0


class SectionTextProvider:
    """Read production answer text from the ES node serving index.

    Runtime chat/search paths should depend on this narrow interface instead of
    opening source PDFs. Runtime PDF extraction remains a caller-controlled debug
    fallback outside this provider.
    """

    def __init__(
        self,
        *,
        settings_obj: Any | None = None,
        embedding_config: Mapping[str, Any] | None = None,
        es_client: Any | None = None,
    ) -> None:
        self.settings = settings_obj or get_settings()
        resolved_embedding_config = dict(
            embedding_config
            or resolve_embedding_config(provider_config={}, embedding_mode="system")
        )
        if not resolved_embedding_config.get("enabled"):
            system_embedding_config = dict(resolve_embedding_config(provider_config={}, embedding_mode="system"))
            if system_embedding_config.get("enabled"):
                resolved_embedding_config = system_embedding_config
        self.embedding_config = resolved_embedding_config
        self.es_client = es_client

    def _client(self) -> tuple[Any | None, str | None]:
        if not bool(getattr(self.settings, "routing_node_es_enabled", False)):
            return None, "es_disabled"
        if self.es_client is not None:
            return self.es_client, None
        return EsNodeDenseSearchBackend()._client(self.settings)

    def _index_name(self, manual_ref: Mapping[str, Any]) -> str | None:
        if not self.embedding_config.get("enabled"):
            return None
        spec_id = embedding_spec_id_for_config(self.embedding_config)
        routing_index_version = _normalize_text(manual_ref.get("routing_index_version")) or "v1"
        index_prefix = (
            _normalize_text(getattr(self.settings, "routing_node_es_index_prefix", None))
            or DEFAULT_NODE_ES_INDEX_PREFIX
        )
        return es_index_name_for_embedding_bundle(
            routing_index_version=routing_index_version,
            embedding_spec_id=spec_id,
            index_prefix=index_prefix,
        )

    def _result_from_source(
        self,
        source: Mapping[str, Any],
        *,
        hit_id: Any = None,
        expected_routing_index_version: str | None = None,
        expected_checksum: str | None = None,
        checksum_mismatch_reason: str | None = None,
        page_start: int | None = None,
        page_end: int | None = None,
    ) -> SectionTextResult:
        text = _normalize_text(source.get("section_text"))
        checksum = _normalize_text(source.get("section_text_checksum"))
        es_routing_index_version = _normalize_text(source.get("routing_index_version"))
        stale = False
        degraded_reason = None
        if not es_routing_index_version:
            stale = True
            degraded_reason = "routing_index_version_missing"
        elif expected_routing_index_version and es_routing_index_version != expected_routing_index_version:
            stale = True
            degraded_reason = "routing_index_version_mismatch"
        elif expected_checksum and checksum and checksum != expected_checksum:
            stale = True
            degraded_reason = checksum_mismatch_reason or "section_text_checksum_mismatch"
        elif expected_checksum and not checksum:
            stale = True
            degraded_reason = "section_text_checksum_missing"

        if stale:
            status = "stale"
            result_source = "stale"
        elif text:
            status = "ready"
            result_source = "es_shadow"
        else:
            status = "missing"
            result_source = "missing"
            degraded_reason = degraded_reason or "section_text_missing"

        return SectionTextResult(
            text=text,
            source=result_source,
            status=status,
            checksum=checksum,
            stale=stale,
            degraded_reason=degraded_reason,
            node_id=_normalize_text(source.get("node_id")),
            node_key=_normalize_text(source.get("node_key") or hit_id),
            page_start=_normalize_int(source.get("page_start")) or page_start,
            page_end=_normalize_int(source.get("page_end")) or page_end,
            title=_normalize_text(source.get("title")),
        )

    def get_for_nodes(
        self,
        manual_ref: Mapping[str, Any],
        nodes: Sequence[Mapping[str, Any]],
    ) -> SectionTextBatch:
        index_name = self._index_name(manual_ref)
        if not index_name:
            return SectionTextBatch(
                records={},
                source="missing",
                status="missing",
                degraded_reason="embedding_config_unavailable",
            )

        client, client_error = self._client()
        if client is None:
            return SectionTextBatch(
                records={},
                source="missing",
                status="missing",
                degraded_reason=client_error or "es_client_unavailable",
                index_name=index_name,
            )

        try:
            if hasattr(client, "indices") and not client.indices.exists(index=index_name):
                return SectionTextBatch(
                    records={},
                    source="missing",
                    status="missing",
                    degraded_reason="es_index_missing",
                    index_name=index_name,
                )
        except Exception as exc:
            return SectionTextBatch(
                records={},
                source="missing",
                status="missing",
                degraded_reason=f"es_index_check_error:{type(exc).__name__}",
                index_name=index_name,
            )

        node_keys = [
            key
            for node in nodes
            if isinstance(node, Mapping)
            if (key := _normalize_text(node.get("node_key")))
        ]
        node_ids = [
            node_id
            for node in nodes
            if isinstance(node, Mapping)
            if (node_id := _normalize_text(node.get("node_id")))
        ]
        nodes_by_identity: dict[str, Mapping[str, Any]] = {}
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            node_key = _normalize_text(node.get("node_key"))
            node_id = _normalize_text(node.get("node_id"))
            if node_key:
                nodes_by_identity[node_key] = node
            if node_id:
                nodes_by_identity[node_id] = node
        if not node_keys and not node_ids:
            return SectionTextBatch(
                records={},
                source="missing",
                status="missing",
                degraded_reason="node_identity_missing",
                index_name=index_name,
            )

        filters: list[dict[str, Any]] = []
        document_id = _normalize_text(manual_ref.get("document_id"))
        version_id = _normalize_text(manual_ref.get("version_id"))
        if document_id:
            filters.append({"term": {"document_id": document_id}})
        if version_id:
            filters.append({"term": {"version_id": version_id}})
        should: list[dict[str, Any]] = []
        if node_keys:
            should.append({"terms": {"node_key": node_keys}})
        if node_ids:
            should.append({"terms": {"node_id": node_ids}})

        body = {
            "size": max(len(node_keys), len(node_ids), 1),
            "_source": [
                "node_key",
                "node_id",
                "title",
                "section_text",
                "page_start",
                "page_end",
                "section_text_checksum",
                "routing_index_version",
            ],
            "query": {
                "bool": {
                    "filter": filters,
                    "should": should,
                    "minimum_should_match": 1,
                }
            },
        }
        try:
            response = client.search(index=index_name, body=body)
        except Exception as exc:
            return SectionTextBatch(
                records={},
                source="missing",
                status="missing",
                degraded_reason=f"es_section_text_search_error:{type(exc).__name__}",
                index_name=index_name,
            )

        records: dict[str, SectionTextResult] = {}
        ready_records = 0
        stale_records = 0
        hits = ((response or {}).get("hits") or {}).get("hits") or []
        for hit in hits:
            if not isinstance(hit, Mapping):
                continue
            source = hit.get("_source") if isinstance(hit.get("_source"), Mapping) else {}
            node_key = _normalize_text(source.get("node_key") or hit.get("_id"))
            node_id = _normalize_text(source.get("node_id"))
            expected_node = nodes_by_identity.get(node_key or "") or nodes_by_identity.get(node_id or "") or {}
            expected_checksum, checksum_reason = _expected_checksum([expected_node, manual_ref])
            expected_routing_index_version = (
                _normalize_text(manual_ref.get("routing_index_version"))
                or _normalize_text(expected_node.get("routing_index_version"))
            )
            record = self._result_from_source(
                source,
                hit_id=hit.get("_id"),
                expected_routing_index_version=expected_routing_index_version,
                expected_checksum=expected_checksum,
                checksum_mismatch_reason=checksum_reason,
            )
            if record.status == "ready":
                ready_records += 1
            elif record.status == "stale":
                stale_records += 1
            if node_key:
                records[node_key] = record
            if node_id:
                records[node_id] = record

        if ready_records:
            batch_source = "es_shadow"
            batch_status = "ready"
            degraded_reason = None
        elif stale_records:
            batch_source = "stale"
            batch_status = "stale"
            stale_reasons = sorted(
                {
                    record.degraded_reason
                    for record in records.values()
                    if record.status == "stale" and record.degraded_reason
                }
            )
            degraded_reason = ",".join(stale_reasons) if stale_reasons else "section_text_stale"
        else:
            batch_source = "missing"
            batch_status = "missing"
            degraded_reason = "section_text_missing"
        return SectionTextBatch(
            records=records,
            source=batch_source,
            status=batch_status,
            degraded_reason=degraded_reason,
            index_name=index_name,
            hit_count=len(hits),
        )

    def get_by_node(
        self,
        *,
        document_id: str,
        version_id: str,
        node_id: str,
        routing_index_version: str | None = None,
        node_key: str | None = None,
    ) -> SectionTextResult:
        batch = self.get_for_nodes(
            {
                "document_id": document_id,
                "version_id": version_id,
                "routing_index_version": routing_index_version,
            },
            [{"node_id": node_id, "node_key": node_key}],
        )
        return (
            batch.records.get(node_key or "")
            or batch.records.get(node_id)
            or SectionTextResult(
                text=None,
                source=batch.source,
                status=batch.status,
                stale=False,
                degraded_reason=batch.degraded_reason,
                node_id=node_id,
                node_key=node_key,
            )
        )

    def get_by_page_span(
        self,
        *,
        document_id: str,
        version_id: str,
        page_start: int,
        page_end: int,
        routing_index_version: str | None = None,
    ) -> SectionTextResult:
        manual_ref = {
            "document_id": document_id,
            "version_id": version_id,
            "routing_index_version": routing_index_version,
        }
        index_name = self._index_name(manual_ref)
        if not index_name:
            return SectionTextResult(
                text=None,
                source="missing",
                status="missing",
                degraded_reason="embedding_config_unavailable",
                page_start=page_start,
                page_end=page_end,
            )
        client, client_error = self._client()
        if client is None:
            return SectionTextResult(
                text=None,
                source="missing",
                status="missing",
                degraded_reason=client_error or "es_client_unavailable",
                page_start=page_start,
                page_end=page_end,
            )
        try:
            if hasattr(client, "indices") and not client.indices.exists(index=index_name):
                return SectionTextResult(
                    text=None,
                    source="missing",
                    status="missing",
                    degraded_reason="es_index_missing",
                    page_start=page_start,
                    page_end=page_end,
                )
        except Exception as exc:
            return SectionTextResult(
                text=None,
                source="missing",
                status="missing",
                degraded_reason=f"es_index_check_error:{type(exc).__name__}",
                page_start=page_start,
                page_end=page_end,
            )
        body = {
            "size": 1,
            "_source": [
                "node_key",
                "node_id",
                "title",
                "section_text",
                "page_start",
                "page_end",
                "section_text_checksum",
                "routing_index_version",
            ],
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"document_id": document_id}},
                        {"term": {"version_id": version_id}},
                        {"range": {"page_start": {"lte": page_start}}},
                        {"range": {"page_end": {"gte": page_end}}},
                    ]
                }
            },
        }
        try:
            response = client.search(index=index_name, body=body)
        except Exception as exc:
            return SectionTextResult(
                text=None,
                source="missing",
                status="missing",
                degraded_reason=f"es_section_text_search_error:{type(exc).__name__}",
                page_start=page_start,
                page_end=page_end,
            )
        hits = ((response or {}).get("hits") or {}).get("hits") or []
        if not hits:
            return SectionTextResult(
                text=None,
                source="missing",
                status="missing",
                degraded_reason="section_text_missing",
                page_start=page_start,
                page_end=page_end,
            )
        source = hits[0].get("_source") if isinstance(hits[0], Mapping) else {}
        return self._result_from_source(
            source,
            hit_id=hits[0].get("_id"),
            expected_routing_index_version=_normalize_text(routing_index_version),
            page_start=page_start,
            page_end=page_end,
        )

    def get_for_citations(self, citations: Sequence[Mapping[str, Any]]) -> list[SectionTextResult]:
        results: list[SectionTextResult] = []
        for citation in citations:
            document_id = _normalize_text(citation.get("document_id"))
            version_id = _normalize_text(citation.get("version_id"))
            node_id = _normalize_text(citation.get("node_id"))
            node_key = _normalize_text(citation.get("node_key"))
            routing_index_version = _normalize_text(citation.get("routing_index_version"))
            if document_id and version_id and node_id:
                batch = self.get_for_nodes(
                    {
                        **dict(citation),
                        "document_id": document_id,
                        "version_id": version_id,
                        "routing_index_version": routing_index_version,
                    },
                    [citation],
                )
                result = (
                    batch.records.get(node_key or "")
                    or batch.records.get(node_id)
                    or SectionTextResult(
                        text=None,
                        source=batch.source,
                        status=batch.status,
                        degraded_reason=batch.degraded_reason,
                        node_id=node_id,
                        node_key=node_key,
                    )
                )
            elif document_id and version_id and citation.get("page_start") and citation.get("page_end"):
                result = self.get_by_page_span(
                    document_id=document_id,
                    version_id=version_id,
                    page_start=int(citation["page_start"]),
                    page_end=int(citation["page_end"]),
                    routing_index_version=routing_index_version,
                )
            else:
                result = SectionTextResult(
                    text=None,
                    source="missing",
                    status="missing",
                    degraded_reason="citation_identity_missing",
                    node_id=node_id,
                    node_key=node_key,
                )
            results.append(result)
        return results


__all__ = ["SectionTextBatch", "SectionTextProvider", "SectionTextResult"]
