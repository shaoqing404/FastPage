import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib import error

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.services.node_embedding_service import (
    EsNodeDenseSearchBackend,
    ExactScanNodeDenseSearchBackend,
    NODE_EMBEDDING_ARTIFACT_SCHEMA_VERSION,
    NODE_EMBEDDING_DENSE_SOURCE_ARTIFACT_EXACT,
    NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW,
    NODE_EMBEDDING_SECTION_TEXT_MAX_CHARS,
    NODE_EMBEDDING_TEXT_SCHEMA_VERSION,
    NodeEmbeddingArtifactResult,
    NodeEmbeddingArtifactStore,
    OpenAICompatibleEmbeddingClient,
    build_node_embedding_text,
    build_es_index_mapping,
    detect_dimension_mismatch,
    embedding_spec_id_for_config,
    ensure_es_index,
    es_index_name_for_embedding_bundle,
    sync_artifact_to_es,
    sync_bundles_to_es,
)


class MemoryArtifactStorage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.payloads: dict[str, dict] = {}

    def _uri(self, *, tenant_id: str, object_path: str) -> str:
        return str(self.data_dir / "tenants" / tenant_id / object_path)

    def write_json(self, data, *, tenant_id: str, object_path: str) -> str:
        uri = self._uri(tenant_id=tenant_id, object_path=object_path)
        self.payloads[uri] = copy.deepcopy(data)
        return uri

    def read_json(self, uri: str):
        return copy.deepcopy(self.payloads[uri])

    def exists(self, uri: str) -> bool:
        return uri in self.payloads


class FakeEmbeddingClient:
    def embed(self, texts):
        vectors = []
        for text in texts:
            lowered = text.lower()
            if "airport" in lowered:
                vectors.append([1.0, 0.0, 0.0])
            elif "fuel" in lowered:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


class BatchFailingEmbeddingClient:
    max_batch_size = 1

    def __init__(self) -> None:
        self.call_count = 0

    def embed(self, texts):
        self.call_count += 1
        if self.call_count == 2:
            raise RuntimeError("provider batch failed with sk-sensitive-value")
        return [[float(self.call_count), 0.0, 0.0] for _text in texts]


class FakeUrlopenResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class TestNodeEmbeddingService(unittest.TestCase):
    def test_build_node_embedding_text_truncates_section_text_for_provider_limits(self):
        text = build_node_embedding_text(
            {"document_label": "Manual"},
            {
                "node_id": "0195",
                "title": "11.2 旅客运输标准和要求",
                "section_text": "正文" * 10000,
            },
        )

        self.assertIn("section_text:", text)
        self.assertIn("section_text truncated for embedding", text)
        self.assertIn("正文" * (NODE_EMBEDDING_SECTION_TEXT_MAX_CHARS // 2), text)
        self.assertNotIn("正文" * ((NODE_EMBEDDING_SECTION_TEXT_MAX_CHARS // 2) + 1), text)

    def _settings(self, data_dir: Path, *, build_mode: str = "enabled", es_enabled: bool = False) -> SimpleNamespace:
        return SimpleNamespace(
            data_dir=data_dir,
            storage_backend="local",
            routing_embeddings_build_mode=build_mode,
            routing_node_es_enabled=es_enabled,
            routing_node_es_url="",
            routing_node_es_index_prefix="pageindex-node-embeddings",
        )

    def _manual(self) -> dict:
        return {
            "tenant_id": "tenant_1",
            "manual_key": "doc_1:ver_1",
            "document_id": "doc_1",
            "version_id": "ver_1",
            "document_label": "Alpha Manual",
            "version_label": "v1",
            "display_name": "Alpha Manual",
            "source_filename": "alpha.pdf",
            "routing_index_version": "routing_v1",
        }

    def _nodes(self) -> list[dict]:
        return [
            {
                "manual_key": "doc_1:ver_1",
                "document_id": "doc_1",
                "version_id": "ver_1",
                "node_id": "n1",
                "node_key": "doc_1:ver_1:n1",
                "title": "Airport Approach",
                "breadcrumb": "Alpha Manual / Airport Approach",
                "page_start": 1,
                "page_end": 2,
                "page_span": 2,
                "depth": 1,
                "route_summary": "Optional airport summary",
            },
            {
                "manual_key": "doc_1:ver_1",
                "document_id": "doc_1",
                "version_id": "ver_1",
                "node_id": "n2",
                "node_key": "doc_1:ver_1:n2",
                "title": "Fuel Planning",
                "breadcrumb": "Alpha Manual / Fuel Planning",
                "page_start": 3,
                "page_end": 5,
                "page_span": 3,
                "depth": 1,
            },
        ]

    def _embedding_config(self) -> dict:
        return {
            "enabled": True,
            "resolved_mode": "system",
            "provider_source": "system",
            "provider_type": "openai_compatible",
            "model": "openai/text-embedding-3-small",
        }

    def test_get_or_build_writes_version_scoped_manifest_and_spec_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))
            storage = MemoryArtifactStorage(Path(temp_dir))
            store = NodeEmbeddingArtifactStore(
                storage=storage,
                settings_obj=settings,
                embedding_client=FakeEmbeddingClient(),
            )

            result = store.get_or_build(
                manual=self._manual(),
                nodes=self._nodes(),
                embedding_config=self._embedding_config(),
            )

        self.assertTrue(result.available)
        self.assertTrue(result.written)
        self.assertEqual(result.bundle["schema_version"], NODE_EMBEDDING_ARTIFACT_SCHEMA_VERSION)
        self.assertEqual(
            result.bundle["bundle_key"],
            {
                "document_id": "doc_1",
                "version_id": "ver_1",
                "routing_index_version": "routing_v1",
                "embedding_spec_id": embedding_spec_id_for_config(self._embedding_config()),
            },
        )
        manifest = result.bundle["manifest"]
        self.assertEqual(manifest["provider_source"], "system")
        self.assertEqual(manifest["provider_type"], "openai_compatible")
        self.assertEqual(manifest["model"], "openai/text-embedding-3-small")
        self.assertEqual(manifest["dimensions"], 3)
        self.assertEqual(manifest["text_schema_version"], NODE_EMBEDDING_TEXT_SCHEMA_VERSION)
        self.assertEqual(manifest["node_count"], 2)
        self.assertEqual(manifest["embedded_node_count"], 2)
        self.assertEqual(manifest["failed_node_count"], 0)
        self.assertEqual(manifest["status"], "complete")
        self.assertTrue(manifest["complete"])
        self.assertEqual(manifest["batch_size"], 10)
        self.assertEqual(manifest["batch_count"], 1)
        self.assertEqual(manifest["failed_batches"], [])
        self.assertEqual(manifest["artifact_layout"], "single_file")
        self.assertFalse(manifest["sharded"])
        self.assertIn("created_at", manifest)
        self.assertIn("text_checksum", manifest)
        self.assertIn("embedding_checksum", manifest)
        self.assertIn("manifest_hash", manifest)
        self.assertIn("/documents/doc_1/versions/ver_1/routing_embeddings/routing_v1/", result.uri)
        self.assertIn("title: Airport Approach", result.bundle["nodes"][0]["text"])
        self.assertIn("breadcrumb: Alpha Manual / Airport Approach", result.bundle["nodes"][0]["text"])
        self.assertIn("page_span: 1-2", result.bundle["nodes"][0]["text"])
        self.assertIn("route_summary: Optional airport summary", result.bundle["nodes"][0]["text"])

    def test_legacy_bundle_is_compatible_when_build_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir), build_mode="disabled")
            storage = MemoryArtifactStorage(Path(temp_dir))
            store = NodeEmbeddingArtifactStore(
                storage=storage,
                settings_obj=settings,
                embedding_client=FakeEmbeddingClient(),
            )
            spec_id = embedding_spec_id_for_config(self._embedding_config())
            uri = store.bundle_uri(
                tenant_id="tenant_1",
                document_id="doc_1",
                version_id="ver_1",
                routing_index_version="routing_v1",
                embedding_spec_id=spec_id,
            )
            storage.payloads[uri] = {
                "schema_version": NODE_EMBEDDING_ARTIFACT_SCHEMA_VERSION,
                "bundle_key": {
                    "document_id": "doc_1",
                    "version_id": "ver_1",
                    "routing_index_version": "routing_v1",
                    "embedding_spec_id": spec_id,
                },
                "manifest": {"node_count": 2},
                "nodes": [
                    {"node_key": "doc_1:ver_1:n1", "embedding": [1.0, 0.0]},
                    {"node_key": "doc_1:ver_1:n2", "embedding": [0.0, 1.0]},
                ],
            }

            result = store.get_or_build(
                manual=self._manual(),
                nodes=self._nodes(),
                embedding_config=self._embedding_config(),
            )

        self.assertTrue(result.available)
        self.assertFalse(result.built)
        self.assertFalse(result.written)
        self.assertTrue(result.bundle["manifest"]["legacy_bundle"])
        self.assertEqual(result.bundle["manifest"]["status"], "complete")

    def test_legacy_bundle_is_refreshed_when_build_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir), build_mode="enabled")
            storage = MemoryArtifactStorage(Path(temp_dir))
            store = NodeEmbeddingArtifactStore(
                storage=storage,
                settings_obj=settings,
                embedding_client=FakeEmbeddingClient(),
            )
            spec_id = embedding_spec_id_for_config(self._embedding_config())
            uri = store.bundle_uri(
                tenant_id="tenant_1",
                document_id="doc_1",
                version_id="ver_1",
                routing_index_version="routing_v1",
                embedding_spec_id=spec_id,
            )
            storage.payloads[uri] = {
                "schema_version": NODE_EMBEDDING_ARTIFACT_SCHEMA_VERSION,
                "bundle_key": {
                    "document_id": "doc_1",
                    "version_id": "ver_1",
                    "routing_index_version": "routing_v1",
                    "embedding_spec_id": spec_id,
                },
                "manifest": {"node_count": 2},
                "nodes": [
                    {"node_key": "doc_1:ver_1:n1", "embedding": [1.0, 0.0]},
                    {"node_key": "doc_1:ver_1:n2", "embedding": [0.0, 1.0]},
                ],
            }

            result = store.get_or_build(
                manual=self._manual(),
                nodes=self._nodes(),
                embedding_config=self._embedding_config(),
            )

        self.assertTrue(result.available)
        self.assertTrue(result.built)
        self.assertTrue(result.written)
        self.assertNotIn("legacy_bundle", result.bundle["manifest"])
        self.assertEqual(result.bundle["manifest"]["status"], "complete")

    def test_exact_scan_scores_artifact_without_es(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))
            store = NodeEmbeddingArtifactStore(
                storage=MemoryArtifactStorage(Path(temp_dir)),
                settings_obj=settings,
                embedding_client=FakeEmbeddingClient(),
            )
            backend = ExactScanNodeDenseSearchBackend(
                artifact_store=store,
                embedding_client=FakeEmbeddingClient(),
            )

            result = backend.search(
                query="airport approach",
                node_corpora=[
                    {
                        "manual": self._manual(),
                        "nodes": self._nodes(),
                    }
                ],
                embedding_mode="system",
                embedding_config=self._embedding_config(),
                settings_obj=settings,
            )

        self.assertTrue(result.enabled)
        self.assertEqual(result.dense_source, NODE_EMBEDDING_DENSE_SOURCE_ARTIFACT_EXACT)
        self.assertGreater(result.dense_scores["doc_1:ver_1:n1"], result.dense_scores["doc_1:ver_1:n2"])
        self.assertEqual(result.metadata()["artifact_count"], 1)

    def test_es_disabled_returns_required_unavailable_without_artifact_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir), es_enabled=False)
            store = NodeEmbeddingArtifactStore(
                storage=MemoryArtifactStorage(Path(temp_dir)),
                settings_obj=settings,
                embedding_client=FakeEmbeddingClient(),
            )
            exact_backend = ExactScanNodeDenseSearchBackend(
                artifact_store=store,
                embedding_client=FakeEmbeddingClient(),
            )
            backend = EsNodeDenseSearchBackend(exact_backend=exact_backend)

            result = backend.search(
                query="airport approach",
                node_corpora=[
                    {
                        "manual": self._manual(),
                        "nodes": self._nodes(),
                    }
                ],
                embedding_mode="system",
                embedding_config=self._embedding_config(),
                settings_obj=settings,
            )

        self.assertFalse(result.enabled)
        self.assertEqual(result.requested_dense_source, NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW)
        self.assertEqual(result.dense_source, NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW)
        self.assertEqual(result.fallback_reason, "es_required_unavailable:es_disabled")
        self.assertEqual(result.es["fallback_reason"], "es_required_unavailable:es_disabled")

    def test_es_index_name_is_scoped_by_routing_version_and_embedding_spec(self):
        index_name = es_index_name_for_embedding_bundle(
            routing_index_version="routing_v1",
            embedding_spec_id="node-emb-abc123",
            index_prefix="PageIndex Nodes",
        )

        self.assertEqual(index_name, "pageindex_nodes-routing_v1-node-emb-abc123")

    def test_openai_compatible_client_batches_embedding_requests(self):
        call_sizes: list[int] = []

        def fake_urlopen(req, timeout):
            payload = json.loads(req.data.decode("utf-8"))
            inputs = list(payload["input"])
            call_sizes.append(len(inputs))
            return FakeUrlopenResponse(
                {
                    "data": [
                        {"embedding": [float(text.rsplit(" ", 1)[1]), 1.0]}
                        for text in inputs
                    ]
                }
            )

        client = OpenAICompatibleEmbeddingClient(
            base_url="https://example.test/v1/embeddings",
            api_key="test-key",
            model="openai/text-embedding-v4",
            provider_type="openai_compatible",
            max_batch_size=10,
        )

        with patch("app.services.node_embedding_service.request.urlopen", side_effect=fake_urlopen):
            vectors = client.embed([f"text {index}" for index in range(25)])

        self.assertEqual(call_sizes, [10, 10, 5])
        self.assertEqual(len(vectors), 25)
        self.assertEqual(vectors[0], [0.0, 1.0])
        self.assertEqual(vectors[13], [13.0, 1.0])
        self.assertEqual(vectors[24], [24.0, 1.0])

    def test_openai_compatible_client_retries_retryable_http_errors(self):
        calls = 0

        def fake_urlopen(req, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise error.HTTPError(
                    url="https://example.test/v1/embeddings",
                    code=429,
                    msg="rate limited",
                    hdrs={},
                    fp=None,
                )
            return FakeUrlopenResponse({"data": [{"embedding": [0.5, 1.0]}]})

        client = OpenAICompatibleEmbeddingClient(
            base_url="https://example.test/v1/embeddings",
            api_key="test-key",
            model="openai/text-embedding-v4",
            provider_type="openai_compatible",
            max_retries=1,
            retry_base_seconds=0,
        )

        with patch("app.services.node_embedding_service.request.urlopen", side_effect=fake_urlopen):
            vectors = client.embed(["retry me"])

        self.assertEqual(calls, 2)
        self.assertEqual(vectors, [[0.5, 1.0]])

    def test_get_or_build_records_failed_batch_without_writing_partial_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir))
            storage = MemoryArtifactStorage(Path(temp_dir))
            store = NodeEmbeddingArtifactStore(
                storage=storage,
                settings_obj=settings,
                embedding_client=BatchFailingEmbeddingClient(),
            )

            result = store.get_or_build(
                manual=self._manual(),
                nodes=self._nodes(),
                embedding_config={**self._embedding_config(), "batch_size": 1},
            )

        self.assertFalse(result.available)
        self.assertFalse(result.written)
        self.assertEqual(storage.payloads, {})
        self.assertEqual(result.fallback_reason, "embedding_provider_error:RuntimeError")
        manifest = result.bundle["manifest"]
        self.assertEqual(manifest["status"], "partial")
        self.assertFalse(manifest["complete"])
        self.assertEqual(manifest["node_count"], 2)
        self.assertEqual(manifest["embedded_node_count"], 1)
        self.assertEqual(manifest["failed_node_count"], 1)
        self.assertEqual(manifest["batch_size"], 1)
        self.assertEqual(manifest["batch_count"], 2)
        self.assertEqual(manifest["failed_batches"][0]["batch_index"], 1)
        self.assertEqual(manifest["failed_batches"][0]["node_ids"], ["n2"])
        self.assertNotIn("sk-sensitive-value", manifest["failed_batches"][0]["message"])
        self.assertEqual(result.bundle["nodes"], [])


class FakeEsIndices:
    """Mock for elasticsearch.client.IndicesClient used in ES index management tests."""

    def __init__(
        self,
        *,
        index_exists: bool = False,
        mapping: dict | None = None,
        create_raises: Exception | None = None,
        exists_raises: Exception | None = None,
    ) -> None:
        self._index_exists = index_exists
        self._mapping = mapping or {}
        self._create_raises = create_raises
        self._exists_raises = exists_raises
        self.created_calls: list[dict] = []

    def exists(self, *, index: str) -> bool:
        if self._exists_raises:
            raise self._exists_raises
        return self._index_exists

    def create(self, *, index: str, body: dict) -> dict:
        if self._create_raises:
            raise self._create_raises
        self.created_calls.append({"index": index, "body": body})
        return {"acknowledged": True}

    def get_mapping(self, *, index: str) -> dict:
        return self._mapping


class FakeEsClient:
    """Mock for elasticsearch.Elasticsearch used in ES backend tests."""

    def __init__(
        self,
        *,
        index_exists: bool = False,
        mapping: dict | None = None,
        search_hits: list[dict] | None = None,
        bulk_errors: list[dict] | None = None,
        search_raises: Exception | None = None,
        bulk_raises: Exception | None = None,
        create_raises: Exception | None = None,
        exists_raises: Exception | None = None,
    ) -> None:
        self.indices = FakeEsIndices(
            index_exists=index_exists,
            mapping=mapping,
            create_raises=create_raises,
            exists_raises=exists_raises,
        )
        self._search_hits = search_hits or []
        self._bulk_errors = bulk_errors or []
        self._search_raises = search_raises
        self._bulk_raises = bulk_raises
        self.search_calls: list[dict] = []
        self.bulk_calls: list[dict] = []

    def search(self, *, index: str, body: dict) -> dict:
        if self._search_raises:
            raise self._search_raises
        self.search_calls.append({"index": index, "body": body})
        return {"hits": {"hits": self._search_hits}}

    def bulk(self, *, body: list, refresh: bool = False) -> dict:
        if self._bulk_raises:
            raise self._bulk_raises
        self.bulk_calls.append({"body": body})
        items = [
            {"index": {"_id": str(i), "result": "indexed"}}
            for i in range(len(body) // 2)
        ]
        if self._bulk_errors:
            items[0] = {"index": {"_id": "err", "error": {"reason": "test error"}}}
        return {"items": items}


def _make_artifact_result(
    *,
    document_id: str = "doc_1",
    version_id: str = "ver_1",
    routing_index_version: str = "routing_v1",
    embedding_spec_id: str = "node-emb-abc",
    tenant_id: str = "tenant_1",
    dims: int = 3,
    node_count: int = 2,
) -> NodeEmbeddingArtifactResult:
    """Build a minimal but complete NodeEmbeddingArtifactResult for testing."""
    nodes = [
        {
            "node_id": f"n{i}",
            "node_key": f"{document_id}:{version_id}:n{i}",
            "document_id": document_id,
            "version_id": version_id,
            "text": f"node {i} text",
            "embedding": [float(j == i % dims) for j in range(dims)],
        }
        for i in range(node_count)
    ]
    bundle = {
        "schema_version": NODE_EMBEDDING_ARTIFACT_SCHEMA_VERSION,
        "bundle_key": {
            "document_id": document_id,
            "version_id": version_id,
            "routing_index_version": routing_index_version,
            "embedding_spec_id": embedding_spec_id,
        },
        "manifest": {
            "status": "complete",
            "complete": True,
            "node_count": node_count,
            "embedded_node_count": node_count,
            "dimensions": dims,
        },
        "nodes": nodes,
    }
    return NodeEmbeddingArtifactResult(
        available=True,
        bundle=bundle,
        uri=f"local://tenants/{tenant_id}/bundle.json",
        object_path=f"tenants/{tenant_id}/bundle.json",
        embedding_spec_id=embedding_spec_id,
    )


class TestEsIndexManagement(unittest.TestCase):
    """Tests for ES index creation, mapping, and dimension mismatch detection."""

    def test_build_es_index_mapping_contains_required_fields(self):
        mapping = build_es_index_mapping(1536)
        props = mapping["mappings"]["properties"]
        required_fields = {
            "tenant_id", "workspace_id", "document_id", "version_id",
            "node_id", "node_key", "embedding_spec_id", "routing_index_version",
            "text", "embedding", "synced_at",
        }
        for field in required_fields:
            self.assertIn(field, props, f"Missing field: {field}")
        self.assertEqual(props["embedding"]["type"], "dense_vector")
        self.assertEqual(props["embedding"]["dims"], 1536)
        self.assertEqual(props["embedding"]["similarity"], "cosine")
        self.assertEqual(props["tenant_id"]["type"], "keyword")
        self.assertEqual(props["workspace_id"]["type"], "keyword")
        self.assertEqual(mapping["settings"]["index"]["max_ngram_diff"], 3)

    def test_ensure_es_index_creates_when_missing(self):
        client = FakeEsClient(index_exists=False)
        result = ensure_es_index(client, "test-index", 768)
        self.assertTrue(result["created"])
        self.assertTrue(result["exists"])
        self.assertTrue(result["dimension_match"])
        self.assertEqual(result["expected_dims"], 768)
        self.assertEqual(result["actual_dims"], 768)
        # Confirm create was called
        self.assertEqual(len(client.indices.created_calls), 1)
        call = client.indices.created_calls[0]
        self.assertEqual(call["index"], "test-index")
        self.assertEqual(call["body"]["mappings"]["properties"]["embedding"]["dims"], 768)

    def test_ensure_es_index_detects_dimension_mismatch(self):
        # Simulate existing index with dims=512 but we expect 768
        mapping = {
            "test-index": {
                "mappings": {
                    "properties": {
                        "embedding": {"type": "dense_vector", "dims": 512}
                    }
                }
            }
        }
        client = FakeEsClient(index_exists=True, mapping=mapping)
        result = ensure_es_index(client, "test-index", 768)
        self.assertFalse(result["created"])
        self.assertTrue(result["exists"])
        self.assertFalse(result["dimension_match"])
        self.assertEqual(result["expected_dims"], 768)
        self.assertEqual(result["actual_dims"], 512)

    def test_ensure_es_index_reports_match_when_dims_agree(self):
        mapping = {
            "test-index": {
                "mappings": {
                    "properties": {
                        "embedding": {"type": "dense_vector", "dims": 768}
                    }
                }
            }
        }
        client = FakeEsClient(index_exists=True, mapping=mapping)
        result = ensure_es_index(client, "test-index", 768)
        self.assertFalse(result["created"])
        self.assertTrue(result["dimension_match"])
        self.assertEqual(result["actual_dims"], 768)

    def test_ensure_es_index_handles_exists_error(self):
        client = FakeEsClient(exists_raises=ConnectionError("es down"))
        result = ensure_es_index(client, "test-index", 768)
        self.assertFalse(result["created"])
        self.assertIsNone(result["exists"])
        self.assertIn("error", result)


class TestArtifactToEsSync(unittest.TestCase):
    """Tests for artifact-to-ES sync (upsert, dry-run, idempotency)."""

    def test_sync_artifact_to_es_upserts_nodes_idempotently(self):
        client = FakeEsClient()
        artifact = _make_artifact_result(node_count=2, dims=3)
        result = sync_artifact_to_es(
            client,
            artifact,
            tenant_id="tenant_1",
            index_name="test-index",
            dry_run=False,
        )
        self.assertEqual(result["synced_count"], 2)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(result["error_count"], 0)
        self.assertFalse(result["dry_run"])
        # Bulk was called once with 2 docs (4 items: 2 action + 2 body)
        self.assertEqual(len(client.bulk_calls), 1)
        bulk_body = client.bulk_calls[0]["body"]
        self.assertEqual(len(bulk_body), 4)  # 2 * (action + doc)
        # Verify _id is node_key
        action_0 = bulk_body[0]
        self.assertIn("index", action_0)
        self.assertEqual(action_0["index"]["_index"], "test-index")
        self.assertIn("doc_1:ver_1:n0", action_0["index"]["_id"])

    def test_sync_artifact_to_es_dry_run_does_not_write(self):
        client = FakeEsClient()
        artifact = _make_artifact_result(node_count=3, dims=3)
        result = sync_artifact_to_es(
            client,
            artifact,
            tenant_id="tenant_1",
            index_name="test-index",
            dry_run=True,
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["synced_count"], 0)
        self.assertEqual(result["would_sync_count"], 3)
        # No bulk calls in dry_run
        self.assertEqual(len(client.bulk_calls), 0)

    def test_sync_artifact_to_es_skips_nodes_without_embedding(self):
        # Build artifact with one node missing embedding
        artifact = _make_artifact_result(node_count=2, dims=3)
        artifact.bundle["nodes"][0]["embedding"] = None  # type: ignore
        client = FakeEsClient()
        result = sync_artifact_to_es(
            client, artifact, tenant_id="tenant_1", index_name="test-index"
        )
        self.assertEqual(result["synced_count"], 1)
        self.assertEqual(result["skipped_count"], 1)

    def test_sync_artifact_to_es_returns_skip_reason_when_unavailable(self):
        client = FakeEsClient()
        artifact = NodeEmbeddingArtifactResult(
            available=False,
            fallback_reason="embedding_build_mode_disabled",
        )
        result = sync_artifact_to_es(
            client, artifact, tenant_id="tenant_1", index_name="test-index"
        )
        self.assertEqual(result["synced_count"], 0)
        self.assertEqual(result["skip_reason"], "artifact_unavailable")
        self.assertEqual(len(client.bulk_calls), 0)

    def test_sync_bundles_to_es_aggregates_across_bundles(self):
        client = FakeEsClient(index_exists=False)
        artifacts = [
            _make_artifact_result(document_id="doc_1", version_id="v1", node_count=2),
            _make_artifact_result(document_id="doc_2", version_id="v2", node_count=3),
        ]
        result = sync_bundles_to_es(
            artifacts,
            client=client,
            tenant_id="tenant_1",
            index_prefix="pageindex-node-embeddings",
            dry_run=False,
        )
        self.assertEqual(result["bundle_count"], 2)
        self.assertEqual(result["total_synced_count"], 5)
        self.assertEqual(result["total_error_count"], 0)
        self.assertFalse(result["dry_run"])


class TestEsSearchWithFilter(unittest.TestCase):
    """Tests for ES search with metadata filters and fallback behavior."""

    def _settings(self, *, es_enabled: bool = True) -> MagicMock:
        s = MagicMock()
        s.routing_node_es_enabled = es_enabled
        s.routing_node_es_url = "http://localhost:9200"
        s.routing_node_es_index_prefix = "pageindex-node-embeddings"
        s.routing_embeddings_build_mode = "enabled"
        s.storage_backend = "local"
        s.data_dir = Path(tempfile.mkdtemp())
        return s

    def _node_corpora(self) -> list[dict]:
        manual = {
            "tenant_id": "tenant_1",
            "manual_key": "doc_1:ver_1",
            "document_id": "doc_1",
            "version_id": "ver_1",
            "routing_index_version": "routing_v1",
        }
        nodes = [
            {
                "node_id": "n1",
                "node_key": "doc_1:ver_1:n1",
                "document_id": "doc_1",
                "version_id": "ver_1",
                "title": "Airport Approach",
                "breadcrumb": "Manual / Airport Approach",
                "page_start": 1,
                "page_end": 2,
            },
        ]
        return [{"manual": manual, "nodes": nodes}]

    def test_es_search_with_metadata_filters_passes_filter_clauses(self):
        # Simulate ES returning one hit
        hits = [
            {
                "_id": "doc_1:ver_1:n1",
                "_score": 0.9,
                "_source": {
                    "node_key": "doc_1:ver_1:n1",
                    "document_id": "doc_1",
                    "version_id": "ver_1",
                },
            }
        ]
        fake_es = FakeEsClient(index_exists=True, search_hits=hits)
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings()
            settings.data_dir = Path(temp_dir)
            store = NodeEmbeddingArtifactStore(
                storage=MemoryArtifactStorage(Path(temp_dir)),
                settings_obj=settings,
                embedding_client=FakeEmbeddingClient(),
            )
            exact_backend = ExactScanNodeDenseSearchBackend(
                artifact_store=store,
                embedding_client=FakeEmbeddingClient(),
            )
            backend = EsNodeDenseSearchBackend(
                exact_backend=exact_backend,
                es_client=fake_es,
            )
            result = backend.search(
                query="airport approach",
                node_corpora=self._node_corpora(),
                embedding_mode="system",
                embedding_config={
                    "enabled": True,
                    "resolved_mode": "system",
                    "provider_source": "system",
                    "provider_type": "openai_compatible",
                    "model": "openai/text-embedding-3-small",
                },
                settings_obj=settings,
            )
        # ES returned a result
        self.assertTrue(result.enabled)
        self.assertEqual(result.dense_source, NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW)
        self.assertIn("doc_1:ver_1:n1", result.dense_scores)
        # Verify filter was applied in the ES search body
        self.assertEqual(len(fake_es.search_calls), 1)
        query_body = fake_es.search_calls[0]["body"]["query"]
        script_query = query_body["script_score"]["query"]
        # With metadata filters, should use bool/filter
        self.assertIn("bool", script_query)
        filter_clauses = script_query["bool"]["filter"]
        filter_keys = [list(c.keys())[0] for c in filter_clauses]
        self.assertIn("terms", filter_keys)  # node_key filter
        self.assertIn("term", filter_keys)   # document_id / version_id / spec_id

    def test_es_search_error_does_not_fallback_to_artifact(self):
        fake_es = FakeEsClient(search_raises=RuntimeError("ES unavailable"))
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings()
            settings.data_dir = Path(temp_dir)
            store = NodeEmbeddingArtifactStore(
                storage=MemoryArtifactStorage(Path(temp_dir)),
                settings_obj=settings,
                embedding_client=FakeEmbeddingClient(),
            )
            exact_backend = ExactScanNodeDenseSearchBackend(
                artifact_store=store,
                embedding_client=FakeEmbeddingClient(),
            )
            backend = EsNodeDenseSearchBackend(
                exact_backend=exact_backend,
                es_client=fake_es,
            )
            result = backend.search(
                query="airport approach",
                node_corpora=self._node_corpora(),
                embedding_mode="system",
                embedding_config={
                    "enabled": True,
                    "resolved_mode": "system",
                    "provider_source": "system",
                    "provider_type": "openai_compatible",
                    "model": "openai/text-embedding-3-small",
                },
                settings_obj=settings,
            )
        self.assertEqual(result.requested_dense_source, NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW)
        self.assertEqual(result.dense_source, NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW)
        self.assertFalse(result.enabled)
        self.assertIn("es_search_error", result.fallback_reason)
        self.assertIn("es_search_error", result.es["fallback_reason"])

    def test_es_dependency_unavailable_fallback(self):
        """When elasticsearch package is missing, EsNodeDenseSearchBackend must safely fallback."""
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(es_enabled=True)
            settings.data_dir = Path(temp_dir)
            # No explicit es_client → will attempt lazy import
            store = NodeEmbeddingArtifactStore(
                storage=MemoryArtifactStorage(Path(temp_dir)),
                settings_obj=settings,
                embedding_client=FakeEmbeddingClient(),
            )
            exact_backend = ExactScanNodeDenseSearchBackend(
                artifact_store=store,
                embedding_client=FakeEmbeddingClient(),
            )
            backend = EsNodeDenseSearchBackend(exact_backend=exact_backend, es_client=None)
            # Patch the elasticsearch import to raise ImportError
            with patch.dict(sys.modules, {"elasticsearch": None}):
                result = backend.search(
                    query="airport approach",
                    node_corpora=self._node_corpora(),
                    embedding_mode="system",
                    embedding_config={
                        "enabled": True,
                        "resolved_mode": "system",
                        "provider_source": "system",
                        "provider_type": "openai_compatible",
                        "model": "openai/text-embedding-3-small",
                    },
                    settings_obj=settings,
                )
        self.assertEqual(result.requested_dense_source, NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW)
        self.assertIn(
            result.fallback_reason,
            {"es_required_unavailable:es_dependency_unavailable", "es_required_unavailable:es_url_missing"},
        )
        self.assertEqual(result.es.get("fallback_reason"), result.fallback_reason)


if __name__ == "__main__":
    unittest.main()
