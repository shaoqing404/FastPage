import pytest
from app.services.node_shadow_service import run_fast_search
from app.services.section_text_provider import SectionTextBatch, SectionTextResult

class MockDocument:
    id = "doc1"
    tenant_id = "tenant1"
    display_name = "test_doc"
    source_filename = "test.pdf"

class MockVersion:
    id = "ver1"
    version_no = 1
    storage_path = "path/to/storage"
    parsed_structure_path = "path/to/structure.json"
    routing_index_status = "synced"
    routing_index_path = "path/to/index.json"
    routing_index_version = "v1"

class MockDenseBackend:
    def __init__(self, mode, scores, metadata):
        self.mode = mode
        self.scores = scores
        self._metadata = metadata

    def search(self, query, node_corpora, embedding_mode, provider_config, embedding_config, settings_obj):
        assert embedding_mode == "system"
        class Result:
            def __init__(self, s, m):
                self.dense_scores = s
                self._m = m
            def metadata(self):
                return self._m
        return Result(self.scores, self._metadata)

def test_run_fast_search_boundary_flags(monkeypatch):
    def mock_build_manual_gate_ref(*args, **kwargs):
        return {"manual_key": "test_doc", "index_version": "v1"}
    monkeypatch.setattr("app.services.routing_consumer_service.build_manual_gate_ref", mock_build_manual_gate_ref)

    def mock_build_node_corpora(*args, **kwargs):
        return []
    monkeypatch.setattr("app.services.node_shadow_service.build_node_corpora", mock_build_node_corpora)

    res = run_fast_search(
        db=None,
        principal=None,
        document=MockDocument(),
        version=MockVersion(),
        query="是否需要下雨天使用？", # Complex query
        top_k=5
    )
    assert "complex_query" in res["boundary_flags"]
    assert res["fallback_recommendation"] == "建议使用 DeepResearch"

def test_run_fast_search_top_k(monkeypatch):
    def mock_build_manual_gate_ref(*args, **kwargs):
        return {"manual_key": "test_doc", "index_version": "v1"}
    monkeypatch.setattr("app.services.routing_consumer_service.build_manual_gate_ref", mock_build_manual_gate_ref)

    def mock_build_node_corpora(*args, **kwargs):
        return []
    monkeypatch.setattr("app.services.node_shadow_service.build_node_corpora", mock_build_node_corpora)

    res = run_fast_search(
        db=None,
        principal=None,
        document=MockDocument(),
        version=MockVersion(),
        query="普通提问",
        top_k=15
    )
    assert res["node_top_k"] == 15
    assert "complex_query" not in res["boundary_flags"]

def test_run_fast_search_dense_sorting(monkeypatch):
    # Provide a mock backend that boosts dense score
    mock_backend = MockDenseBackend(
        mode="hybrid",
        scores={"test_doc:node1": 0.9, "test_doc:node2": 0.1},
        metadata={"dense_source": "es_shadow", "es": {"used": True}, "resolved_mode": "hybrid"}
    )

    def mock_build_manual_gate_ref(*args, **kwargs):
        return {"manual_key": "test_doc", "index_version": "v1"}
    monkeypatch.setattr("app.services.routing_consumer_service.build_manual_gate_ref", mock_build_manual_gate_ref)

    def mock_build_node_corpora(db, manual_refs):
        return [{
            "manual_key": "test_doc",
            "corpus_source": "document_routing_nodes",
            "nodes": [
                {"node_id": "node1", "node_key": "test_doc:node1", "manual_key": "test_doc", "title": "Node 1", "route_summary": "Summary 1", "page_start": 1, "page_end": 1},
                {"node_id": "node2", "node_key": "test_doc:node2", "manual_key": "test_doc", "title": "Node 2", "route_summary": "Summary 2", "page_start": 2, "page_end": 2}
            ]
        }]

    monkeypatch.setattr("app.services.node_shadow_service.build_node_corpora", mock_build_node_corpora)

    res = run_fast_search(
        db=None,
        principal=None,
        document=MockDocument(),
        version=MockVersion(),
        query="普通提问",
        top_k=2,
        dense_search_backend=mock_backend
    )

    assert res["active_backend"] == "es_shadow"
    assert len(res["nodes"]) == 2
    # node1 should have a higher score and be sorted first due to dense score
    assert res["nodes"][0]["node_id"] == "node1"
    assert res["nodes"][0]["score"] > res["nodes"][1]["score"]

def test_run_fast_search_body_term_regression_for_unaccompanied_child(monkeypatch):
    def mock_build_manual_gate_ref(*args, **kwargs):
        return {
            "manual_key": "test_doc",
            "document_id": "doc1",
            "version_id": "ver1",
            "document_label": "RTX_PRO_6000测试报告",
            "storage_path": "missing.pdf",
        }
    monkeypatch.setattr("app.services.routing_consumer_service.build_manual_gate_ref", mock_build_manual_gate_ref)

    distractors = [
        ("0101", "8.4.8.5 出入境手续及相关规定", "出入境手续 证件 检查 海关 边防"),
        ("0102", "8.2.6.3 臭氧浓度限制", "臭氧浓度 限制 通风 飞行高度"),
        ("0103", "8.1.10 机上指挥权的接替", "机长 指挥权 接替 运行控制"),
        ("0104", "8.4.13.5 维修调机", "维修 调机 航班 运行"),
        ("0105", "8.4.10 无人烟地区飞行", "无人烟地区 飞行 生存设备"),
    ]

    def mock_build_node_corpora(db, manual_refs):
        return [{
            "manual_key": "test_doc",
            "manual": manual_refs[0],
            "corpus_source": "document_routing_nodes",
            "nodes": [
                *[
                    {
                        "node_id": node_id,
                        "node_key": f"test_doc:{node_id}",
                        "manual_key": "test_doc",
                        "document_id": "doc1",
                        "version_id": "ver1",
                        "title": title,
                        "route_summary": summary,
                        "page_start": index,
                        "page_end": index,
                    }
                    for index, (node_id, title, summary) in enumerate(distractors, start=800)
                ],
                {
                    "node_id": "0195",
                    "node_key": "test_doc:0195",
                    "manual_key": "test_doc",
                    "document_id": "doc1",
                    "version_id": "ver1",
                    "title": "11.2 旅客运输标准和要求",
                    "route_summary": "旅客运输标准、特殊旅客承运和服务要求。",
                    "page_start": 933,
                    "page_end": 950,
                    "section_text": (
                        "<physical_index_938>\n"
                        "无成人陪伴儿童：10个。其中5（含）-10岁不得超过5个；"
                        "如按扩展限制可承运18个。\n"
                        "<physical_index_938>"
                    ),
                },
            ],
        }]
    monkeypatch.setattr("app.services.node_shadow_service.build_node_corpora", mock_build_node_corpora)

    res = run_fast_search(
        db=None,
        principal=None,
        document=MockDocument(),
        version=MockVersion(),
        query="同一航班上，无成人陪伴儿童（8 岁）最多可承运几名？其中 5 至 10 岁年龄段有何特别限制？",
        top_k=10,
    )

    node_ids = [node["node_id"] for node in res["nodes"]]
    assert "0195" in node_ids
    target = next(node for node in res["nodes"] if node["node_id"] == "0195")
    assert target["title"] == "11.2 旅客运输标准和要求"
    assert target["page_start"] == 933
    assert target["page_end"] == 950

def test_artifact_exact_metadata_is_not_product_backend(monkeypatch):
    mock_backend = MockDenseBackend(
        mode="hybrid",
        scores={"test_doc:node1": 0.5},
        metadata={"dense_source": "artifact_exact_scan", "resolved_mode": "hybrid"}
    )

    def mock_build_manual_gate_ref(*args, **kwargs):
        return {"manual_key": "test_doc", "index_version": "v1"}
    monkeypatch.setattr("app.services.routing_consumer_service.build_manual_gate_ref", mock_build_manual_gate_ref)

    def mock_build_node_corpora(db, manual_refs):
        return [{
            "manual_key": "test_doc",
            "corpus_source": "document_routing_nodes",
            "nodes": [
                {"node_id": "node1", "node_key": "test_doc:node1", "manual_key": "test_doc", "title": "Node 1", "route_summary": "Summary 1", "page_start": 1, "page_end": 1}
            ]
        }]

    monkeypatch.setattr("app.services.node_shadow_service.build_node_corpora", mock_build_node_corpora)

    res = run_fast_search(
        db=None,
        principal=None,
        document=MockDocument(),
        version=MockVersion(),
        query="普通提问",
        top_k=5,
        dense_search_backend=mock_backend
    )

    assert res["active_backend"] == "lexical_fallback"
    assert res["artifact_exact_scan_executed"] is False


def test_fast_search_missing_es_section_text_does_not_extract_pdf(monkeypatch):
    def mock_build_manual_gate_ref(*args, **kwargs):
        return {
            "manual_key": "test_doc",
            "document_id": "doc1",
            "version_id": "ver1",
            "storage_path": "missing.pdf",
        }
    monkeypatch.setattr("app.services.routing_consumer_service.build_manual_gate_ref", mock_build_manual_gate_ref)

    def mock_build_node_corpora(db, manual_refs):
        return [{
            "manual_key": "test_doc",
            "manual": manual_refs[0],
            "corpus_source": "document_routing_nodes",
            "nodes": [
                {
                    "node_id": "node1",
                    "node_key": "test_doc:node1",
                    "manual_key": "test_doc",
                    "title": "Node 1",
                    "route_summary": "Summary 1",
                    "page_start": 1,
                    "page_end": 1,
                }
            ],
        }]
    monkeypatch.setattr("app.services.node_shadow_service.build_node_corpora", mock_build_node_corpora)

    def mock_get_for_nodes(self, manual_ref, nodes):
        return SectionTextBatch(
            records={},
            source="missing",
            status="missing",
            degraded_reason="es_index_missing",
        )
    monkeypatch.setattr("app.services.section_text_provider.SectionTextProvider.get_for_nodes", mock_get_for_nodes)

    def fail_pdf(*args, **kwargs):
        raise AssertionError("runtime PDF extraction should not run")
    monkeypatch.setattr("app.services.node_shadow_service.get_page_tokens", fail_pdf)

    res = run_fast_search(
        db=None,
        principal=None,
        document=MockDocument(),
        version=MockVersion(),
        query="普通提问",
        top_k=5,
    )

    assert res["section_text_node_count"] == 0
    assert res["section_text_source"] == "missing"
    assert res["section_text_degraded_reason"] == "es_index_missing"
    assert res["fallback_recommendation"] == "FastSearch data not ready; use DeepResearch or rebuild fast index"
    assert res["runtime_pdf_fallback_allowed"] is False


def test_fast_search_es_ready_does_not_extract_pdf(monkeypatch):
    def mock_build_manual_gate_ref(*args, **kwargs):
        return {
            "manual_key": "test_doc",
            "document_id": "doc1",
            "version_id": "ver1",
            "storage_path": "missing.pdf",
        }
    monkeypatch.setattr("app.services.routing_consumer_service.build_manual_gate_ref", mock_build_manual_gate_ref)

    def mock_build_node_corpora(db, manual_refs):
        return [{
            "manual_key": "test_doc",
            "manual": manual_refs[0],
            "corpus_source": "document_routing_nodes",
            "nodes": [
                {
                    "node_id": "node1",
                    "node_key": "test_doc:node1",
                    "manual_key": "test_doc",
                    "title": "Node 1",
                    "route_summary": "Summary 1",
                    "page_start": 1,
                    "page_end": 1,
                }
            ],
        }]
    monkeypatch.setattr("app.services.node_shadow_service.build_node_corpora", mock_build_node_corpora)

    def mock_get_for_nodes(self, manual_ref, nodes):
        return SectionTextBatch(
            records={
                "test_doc:node1": SectionTextResult(
                    text="ES section text",
                    source="es_shadow",
                    status="ready",
                    node_id="node1",
                    node_key="test_doc:node1",
                    page_start=1,
                    page_end=1,
                )
            },
            source="es_shadow",
            status="ready",
        )
    monkeypatch.setattr("app.services.section_text_provider.SectionTextProvider.get_for_nodes", mock_get_for_nodes)

    def fail_pdf(*args, **kwargs):
        raise AssertionError("runtime PDF extraction should not run")
    monkeypatch.setattr("app.services.node_shadow_service.get_page_tokens", fail_pdf)

    res = run_fast_search(
        db=None,
        principal=None,
        document=MockDocument(),
        version=MockVersion(),
        query="ES section",
        top_k=5,
    )

    assert res["section_text_node_count"] == 1
    assert res["section_text_source"] == "es_shadow"
    assert res["section_text_participated"] is True
    assert res["runtime_pdf_fallback_allowed"] is False


def test_fast_search_stale_es_section_text_is_degraded(monkeypatch):
    def mock_build_manual_gate_ref(*args, **kwargs):
        return {
            "manual_key": "test_doc",
            "document_id": "doc1",
            "version_id": "ver1",
            "storage_path": "missing.pdf",
            "routing_index_version": "v2",
        }
    monkeypatch.setattr("app.services.routing_consumer_service.build_manual_gate_ref", mock_build_manual_gate_ref)

    def mock_build_node_corpora(db, manual_refs):
        return [{
            "manual_key": "test_doc",
            "manual": manual_refs[0],
            "corpus_source": "document_routing_nodes",
            "nodes": [
                {
                    "node_id": "node1",
                    "node_key": "test_doc:node1",
                    "manual_key": "test_doc",
                    "title": "Node 1",
                    "route_summary": "Summary 1",
                    "page_start": 1,
                    "page_end": 1,
                }
            ],
        }]
    monkeypatch.setattr("app.services.node_shadow_service.build_node_corpora", mock_build_node_corpora)

    def mock_get_for_nodes(self, manual_ref, nodes):
        return SectionTextBatch(
            records={
                "test_doc:node1": SectionTextResult(
                    text="stale ES text",
                    source="stale",
                    status="stale",
                    stale=True,
                    degraded_reason="routing_index_version_mismatch",
                    node_id="node1",
                    node_key="test_doc:node1",
                )
            },
            source="stale",
            status="stale",
            degraded_reason="routing_index_version_mismatch",
        )
    monkeypatch.setattr("app.services.section_text_provider.SectionTextProvider.get_for_nodes", mock_get_for_nodes)

    def fail_pdf(*args, **kwargs):
        raise AssertionError("runtime PDF extraction should not run")
    monkeypatch.setattr("app.services.node_shadow_service.get_page_tokens", fail_pdf)

    res = run_fast_search(
        db=None,
        principal=None,
        document=MockDocument(),
        version=MockVersion(),
        query="普通提问",
        top_k=5,
    )

    assert res["section_text_node_count"] == 0
    assert res["section_text_source"] == "stale"
    assert res["section_text_degraded_reason"] == "routing_index_version_mismatch"
    assert res["fallback_recommendation"] == "FastSearch data not ready; use DeepResearch or rebuild fast index"
