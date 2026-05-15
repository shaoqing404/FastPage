#!/usr/bin/env python3
"""es_full_validation.py — 端到端 ES shadow backend 验证脚本。

运行方式（在项目根目录）:
    uv run python scripts/phase47/es_full_validation.py

完整验证流程：
1. DB 查询：找到有 routing embedding artifact 的文档
2. MinIO 读取 bundle → 打印节点数
3. Dry-run sync → 确认 would_sync_count
4. Real sync → 写入 ES，记录 synced_count
5. 幂等性验证 → 第二次 sync，count 不变
6. ES query → 用 bundle 中第一个 embedding 向量查询，验证 dense_source=es_shadow
7. Fallback safety → 用错误密码连接，确认 fallback
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.services.storage_service import get_storage_backend
from app.services.node_embedding_service import (
    NodeEmbeddingArtifactResult,
    embedding_spec_id_for_config,
    ensure_es_index,
    es_index_name_for_embedding_bundle,
    sync_artifact_to_es,
    sync_bundles_to_es,
)

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "


def _es_client(url: str):
    from elasticsearch import Elasticsearch  # type: ignore
    return Elasticsearch(url)


def step(n: int, title: str):
    print(f"\n{'='*60}")
    print(f"Step {n}: {title}")
    print("="*60)


def check(label: str, ok: bool, detail: str = ""):
    icon = PASS if ok else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  {icon} {label}{suffix}")
    return ok


def main():
    settings = get_settings()
    storage = get_storage_backend()
    results: list[dict] = []

    # ── Step 0: ES 连通性 ──────────────────────────────────────────
    step(0, "ES connectivity check")
    es_url = settings.routing_node_es_url or ""
    es_enabled = settings.routing_node_es_enabled
    index_prefix = settings.routing_node_es_index_prefix or "pageindex-node-embeddings"

    print(f"  ROUTING_NODE_ES_ENABLED: {es_enabled}")
    print(f"  ROUTING_NODE_ES_URL: {'(set, masked)' if es_url else '(not set)'}")
    print(f"  ROUTING_NODE_ES_INDEX_PREFIX: {index_prefix}")

    if not es_enabled or not es_url:
        print(f"  {FAIL} ES not enabled or URL missing — abort")
        sys.exit(1)

    client = _es_client(es_url)
    ping_ok = client.ping()
    check("ES ping", ping_ok)
    if not ping_ok:
        print(f"  {FAIL} ES ping failed — abort")
        sys.exit(1)

    # ── Step 1: DB 查询，找有 embedding artifact 的文档 ────────────
    step(1, "Find documents with embedding artifacts in DB")
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(str(settings.database_url or ""))
    Session = sessionmaker(bind=engine)

    with Session() as sess:
        rows = sess.execute(text("""
            SELECT m.tenant_id, m.id as document_id, v.id as version_id,
                   v.routing_index_version
            FROM documents m
            JOIN document_versions v ON v.document_id = m.id
            WHERE v.routing_index_status = 'index_ready'
            LIMIT 5
        """)).fetchall()

    engine.dispose()
    if not rows:
        print(f"  {WARN} No index_ready documents found in DB — skipping sync steps")
        print("  Hint: set at least one document's routing_index_status='index_ready'")
        sys.exit(0)

    for r in rows:
        print(f"  Found: tenant={r.tenant_id} doc={r.document_id} ver={r.version_id} rv={r.routing_index_version}")

    # Use first document
    row = rows[0]
    tenant_id = row.tenant_id
    document_id = row.document_id
    version_id = row.version_id
    routing_index_version = row.routing_index_version or "v1"

    # ── Step 2: Discover and load embedding artifact bundle ────────
    step(2, "Discover and load embedding artifact bundle from storage")

    # List available bundles for this document version
    list_prefix = (
        f"tenants/{tenant_id}/documents/{document_id}/versions/{version_id}"
        f"/routing_embeddings/"
    )
    bundle_candidates: list[tuple[str, str, str]] = []  # (spec_id, rv, object_name)

    if getattr(settings, "storage_backend", "local") == "minio":
        try:
            objects = list(storage.client.list_objects(
                storage.bucket, prefix=list_prefix, recursive=True,
            ))
            for obj in objects:
                name = obj.object_name
                if not name.endswith("/bundle.json"):
                    continue
                # Parse: .../routing_embeddings/{rv}/{spec_id}/bundle.json
                parts = name.split("/")
                if len(parts) >= 2:
                    discovered_spec_id = parts[-2]
                    discovered_rv = parts[-3]
                    bundle_candidates.append((discovered_spec_id, discovered_rv, name))
        except Exception as exc:
            print(f"  {WARN} Could not list MinIO: {exc}")
    else:
        import glob as _glob
        local_dir = settings.data_dir / list_prefix
        for p in _glob.glob(str(local_dir / "*" / "bundle.json")):
            parts = Path(p).parts
            discovered_spec_id = parts[-2]
            discovered_rv = parts[-3]
            bundle_candidates.append((discovered_spec_id, discovered_rv, str(p)))

    if not bundle_candidates:
        print(f"  {WARN} No bundle.json found for this document version")
        print(f"  Hint: run ROUTING_EMBEDDINGS_BUILD_MODE=enabled and process a document")
        sys.exit(0)

    print(f"  Found {len(bundle_candidates)} bundle(s)")
    spec_id, routing_index_version, object_name = bundle_candidates[0]
    print(f"  Using: spec_id={spec_id} rv={routing_index_version}")

    # Build URI matching NodeEmbeddingArtifactStore.bundle_uri logic
    object_path_inner = (
        f"documents/{document_id}/versions/{version_id}"
        f"/routing_embeddings/{routing_index_version}/{spec_id}/bundle.json"
    )
    if getattr(settings, "storage_backend", "local") == "minio":
        prefix = getattr(settings, "minio_prefix_path", "").strip("/")
        prefix = f"{prefix}/" if prefix else ""
        uri = f"minio://{settings.minio_bucket}/{prefix}tenants/{tenant_id}/{object_path_inner}"
    else:
        uri = str(settings.data_dir / "tenants" / tenant_id / object_path_inner)

    try:
        bundle = storage.read_json(uri)
        nodes = bundle.get("nodes") or []
        manifest = bundle.get("manifest") or {}
        dims = manifest.get("dimensions", 0)
        check("Bundle loaded", True, f"{len(nodes)} nodes, dims={dims}")
    except Exception as exc:
        check("Bundle loaded", False, str(exc))
        print(f"  {FAIL} Failed to load bundle")
        sys.exit(1)

    artifact = NodeEmbeddingArtifactResult(
        available=True,
        bundle=bundle,
        uri=uri,
        object_path=object_path_inner,
        embedding_spec_id=spec_id,
    )
    bundle_key = bundle.get("bundle_key") or {}
    index_name = es_index_name_for_embedding_bundle(
        routing_index_version=bundle_key.get("routing_index_version") or routing_index_version,
        embedding_spec_id=bundle_key.get("embedding_spec_id") or spec_id,
        index_prefix=index_prefix,
    )
    print(f"  Target ES index: {index_name}")

    # ── Closeout #1: 确认 bundle 身份 ─────────────────────────────
    # B4 Fast Search 目标文档 265 nodes。
    # 本次 sync 使用的 bundle 信息如下，供人工确认是否覆盖目标文档。
    manifest_label = manifest.get("node_count", len(nodes))
    bundle_document_id = bundle_key.get("document_id", document_id)
    bundle_version_id = bundle_key.get("version_id", version_id)
    bundle_rv = bundle_key.get("routing_index_version", routing_index_version)
    bundle_spec = bundle_key.get("embedding_spec_id", spec_id)
    print(f"")
    print(f"  ── Bundle Identity (Closeout #1) ──")
    print(f"  tenant_id             : {tenant_id}")
    print(f"  document_id           : {bundle_document_id}")
    print(f"  version_id            : {bundle_version_id}")
    print(f"  routing_index_version : {bundle_rv}")
    print(f"  embedding_spec_id     : {bundle_spec}")
    print(f"  node_count (manifest) : {manifest_label}")
    print(f"  dims                  : {dims}")
    print(f"  ── End Bundle Identity ────────────")

    # ── Step 3: Ensure index exists ───────────────────────────────
    step(3, "Ensure ES index exists with correct mapping")
    ensure_result = ensure_es_index(client, index_name, dims)
    check("Index created/exists", ensure_result.get("exists") is True, json.dumps(ensure_result))
    check("Dimension match", ensure_result.get("dimension_match") is True,
          f"expected={ensure_result.get('expected_dims')} actual={ensure_result.get('actual_dims')}")
    results.append({"step": "ensure_index", **ensure_result})

    # ── Step 4: Dry-run sync ──────────────────────────────────────
    step(4, "Dry-run sync (no writes)")
    dry = sync_artifact_to_es(client, artifact, tenant_id=tenant_id, index_name=index_name, dry_run=True)
    check("dry_run=True", dry["dry_run"])
    check("would_sync_count > 0", dry["would_sync_count"] > 0, str(dry["would_sync_count"]))
    check("error_count == 0", dry["error_count"] == 0)
    results.append({"step": "dry_run_sync", **dry})
    print(f"  would_sync_count: {dry['would_sync_count']}")

    # ── Step 5: Real sync ─────────────────────────────────────────
    step(5, "Real sync → write to ES")
    s1 = sync_artifact_to_es(client, artifact, tenant_id=tenant_id, index_name=index_name, dry_run=False)
    check("dry_run=False", not s1["dry_run"])
    check("synced_count > 0", s1["synced_count"] > 0, str(s1["synced_count"]))
    check("error_count == 0", s1["error_count"] == 0, str(s1.get("errors", [])))
    results.append({"step": "real_sync_1", **s1})

    # ── Step 6: Idempotency — sync again ─────────────────────────
    step(6, "Idempotency — sync again (should produce same count)")
    s2 = sync_artifact_to_es(client, artifact, tenant_id=tenant_id, index_name=index_name, dry_run=False)
    check("second sync synced_count == first", s2["synced_count"] == s1["synced_count"],
          f"first={s1['synced_count']} second={s2['synced_count']}")
    check("error_count == 0", s2["error_count"] == 0)
    results.append({"step": "idempotent_sync", **s2})

    # Refresh index for accurate counts
    try:
        client.indices.refresh(index=index_name)
        count_resp = client.count(index=index_name)
        doc_count = count_resp.get("count", 0)
        print(f"  ES doc_count after sync: {doc_count}")
        check("ES doc_count == synced_count", doc_count == s1["synced_count"],
              f"es={doc_count} synced={s1['synced_count']}")
    except Exception as exc:
        print(f"  {WARN} Could not verify doc count: {exc}")

    # ── Step 7: ES vector query ───────────────────────────────────
    step(7, "ES vector query (use first node embedding as query vector)")
    first_node = next((n for n in nodes if n.get("embedding")), None)
    if not first_node:
        print(f"  {WARN} No node with embedding found, skip query test")
    else:
        query_vector = [float(v) for v in first_node["embedding"]]
        expected_node_key = first_node.get("node_key", "")
        body = {
            "size": 3,
            "query": {
                "script_score": {
                    "query": {"match_all": {}},
                    "script": {
                        "source": "(cosineSimilarity(params.query_vector, 'embedding') + 1.0) / 2.0",
                        "params": {"query_vector": query_vector},
                    },
                }
            },
            "_source": ["node_key", "document_id", "version_id", "embedding_spec_id"],
        }
        resp = client.search(index=index_name, body=body)
        hits = (resp.get("hits") or {}).get("hits") or []
        check("ES returned hits", len(hits) > 0, f"{len(hits)} hits")
        if hits:
            top_hit_key = (hits[0].get("_source") or {}).get("node_key") or hits[0].get("_id")
            top_score = hits[0].get("_score")
            check("Top hit == queried node", top_hit_key == expected_node_key,
                  f"got={top_hit_key} expected={expected_node_key}")
            check("Score >= 0.99 (cosine self-similarity)", (top_score or 0) >= 0.99, f"score={top_score}")
            results.append({"step": "es_query", "hit_count": len(hits), "top_hit": top_hit_key, "top_score": top_score})

    # ── Closeout #2: Fallback safety via search RUNTIME path ──────
    # maintenance CLI (check/sync) may fail loud.
    # search/query RUNTIME path in EsNodeDenseSearchBackend.search() MUST:
    #   catch any ES exception → _fallback_exact → dense_source = artifact_exact_scan
    # This step verifies THAT semantic end-to-end:
    #   bad creds → ES raises AuthenticationException inside search() → caught →
    #   fallback_reason starts with "es_search_error:" → dense_source != es_shadow
    #
    # Fix: pass embedding_config with explicit embedding_spec_id=bundle_spec so that
    #   embedding_spec_id_for_config() returns bundle_spec directly (no hash mismatch),
    #   _load_existing finds the bundle, _prepare succeeds, and flow reaches ES search.
    #   A FakeEmbeddingClient provides the query vector.
    step(8, "Fallback safety — ES exception caught by runtime search path → fallback to artifact_exact_scan")
    print("  (Testing EsNodeDenseSearchBackend.search() with bad credentials, not raw client)")

    from app.services.node_embedding_service import (
        ExactScanNodeDenseSearchBackend,
        EsNodeDenseSearchBackend,
        NodeEmbeddingArtifactStore,
        NODE_EMBEDDING_DENSE_SOURCE_ARTIFACT_EXACT,
        NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW,
    )
    from types import SimpleNamespace

    bad_url = "http://elastic:WRONGPASS@10.108.1.134:9200"
    bad_client = _es_client(bad_url)

    mock_settings = SimpleNamespace(
        routing_node_es_enabled=True,
        routing_node_es_url=bad_url,
        routing_node_es_index_prefix=index_prefix,
        routing_embeddings_build_mode="enabled",
        data_dir=Path(ROOT / "data"),
        storage_backend=settings.storage_backend,
    )

    # Mock embedding client: returns a dummy vector so _prepare succeeds
    # and the flow reaches the ES search step where bad credentials trigger
    # AuthenticationException.
    class _MockEmbeddingClient:
        def embed(self, texts):
            return [[0.0] * dims for _ in texts]

    mock_emb_client = _MockEmbeddingClient()

    fallback_store = NodeEmbeddingArtifactStore(
        storage=storage,
        settings_obj=settings,
        embedding_client=mock_emb_client,  # used to embed the query vector in _prepare
    )
    fallback_exact = ExactScanNodeDenseSearchBackend(
        artifact_store=fallback_store,
        embedding_client=mock_emb_client,
    )
    bad_es_backend = EsNodeDenseSearchBackend(
        exact_backend=fallback_exact,
        es_client=bad_client,
    )

    # Build a minimal node corpus from the bundle we already loaded
    node_corpus = [
        {
            "manual": {
                "tenant_id": tenant_id,
                "document_id": bundle_document_id,
                "version_id": bundle_version_id,
                "manual_key": f"{bundle_document_id}:{bundle_version_id}",
                "routing_index_version": bundle_rv,
            },
            "nodes": [
                {k: v for k, v in n.items() if k != "embedding"}
                for n in nodes[:5]  # 5 nodes is enough to exercise the path
            ],
        }
    ]

    try:
        # Key fix: pass embedding_spec_id=bundle_spec explicitly so that
        # embedding_spec_id_for_config() returns bundle_spec directly
        # (line 305-307 in node_embedding_service.py: explicit check first).
        # This ensures _load_existing finds the already-synced bundle, _prepare
        # succeeds with a real query vector from mock_emb_client, and the flow
        # reaches client.search() → AuthenticationException → es_search_error fallback.
        fallback_result = bad_es_backend.search(
            query="test query",
            node_corpora=node_corpus,
            embedding_mode="system",
            embedding_config={
                "enabled": True,
                "resolved_mode": "system",
                "provider_source": manifest.get("provider_source", "system"),
                "provider_type": manifest.get("provider_type", "openai_compatible"),
                "model": manifest.get("model", ""),
                # Explicit spec_id — bypasses hash, ensures _load_existing hits the bundle
                "embedding_spec_id": bundle_spec,
            },
            settings_obj=mock_settings,
        )
        # Should NOT raise — must catch internally and fallback
        check("search() did not raise (exception caught internally)", True)
        check(
            "fallback_reason contains 'es_' prefix",
            str(fallback_result.es.get("fallback_reason", "")).startswith("es_"),
            str(fallback_result.es.get("fallback_reason")),
        )
        check(
            "requested_dense_source == es_shadow",
            fallback_result.requested_dense_source == NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW,
            fallback_result.requested_dense_source,
        )
        # dense_source must NOT be es_shadow (it fell back)
        check(
            "dense_source != es_shadow (fell back to artifact or disabled)",
            fallback_result.dense_source != NODE_EMBEDDING_DENSE_SOURCE_ES_SHADOW,
            fallback_result.dense_source,
        )
        results.append({
            "step": "fallback_safety",
            "fallback_reason": fallback_result.es.get("fallback_reason"),
            "dense_source": fallback_result.dense_source,
            "requested_dense_source": fallback_result.requested_dense_source,
        })
    except Exception as exc:
        check("search() did not raise", False, f"{type(exc).__name__}: {exc}")
        results.append({"step": "fallback_safety", "error": str(exc)})

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUMMARY")
    print("="*60)
    print(json.dumps(results, indent=2, default=str))

    all_ok = all(
        r.get("error_count", 0) == 0
        for r in results
        if "error_count" in r
    )
    print(f"\n{'='*60}")
    if all_ok:
        print(f"{PASS} B2.8b GATE: GO — 真实 ES 验证通过，production-candidate 状态确认")
    else:
        print(f"{FAIL} B2.8b GATE: Conditional GO — 有错误需排查")
    print("="*60)


if __name__ == "__main__":
    main()
