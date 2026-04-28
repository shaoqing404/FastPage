import asyncio
import os
import sys
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
_pypdf2_mock = sys.modules.get("PyPDF2")
if _pypdf2_mock is None or not hasattr(_pypdf2_mock, "PdfReader"):
    _pypdf2_mock = MagicMock()
    _pypdf2_mock.PdfReader = MagicMock()
    sys.modules["PyPDF2"] = _pypdf2_mock
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.services.pageindex_service import (
    build_context_from_citations_async,
    build_answer_context,
    choose_relevant_nodes,
    load_structure_file,
    merge_candidates_round_robin,
    snapshot_outline_diagnostics,
)
from app.services.section_text_provider import SectionTextProvider, SectionTextResult
from pageindex.utils import run_reuse_scope
import pageindex.utils as pageindex_utils

if pageindex_utils.PyPDF2 is None or not hasattr(pageindex_utils.PyPDF2, "PdfReader"):
    pageindex_utils.PyPDF2 = _pypdf2_mock


class _RecordingArtifactBackend:
    def __init__(self, *, json_payload: dict | None = None, pdf_path: str = "/tmp/shared.pdf") -> None:
        self.json_payload = json_payload or {"structure": []}
        self.pdf_path = Path(pdf_path)
        self.read_json_calls = 0
        self.local_path_calls = 0
        self._lock = threading.Lock()

    def read_json(self, uri: str):
        with self._lock:
            self.read_json_calls += 1
        return self.json_payload

    @contextmanager
    def local_path(self, uri: str):
        with self._lock:
            self.local_path_calls += 1
        yield self.pdf_path


class _LocalPassthroughBackend:
    @contextmanager
    def local_path(self, uri: str):
        yield Path(uri)


class TestPageIndexRetrievalContract(unittest.TestCase):
    @patch("app.services.pageindex_service.llm_completion")
    def test_outline_prompt_uses_runtime_candidate_limit(self, mock_completion):
        mock_completion.return_value = "{\"node_ids\": [\"0001\"], \"why\": \"specific\"}"

        structure = [
            {"node_id": "0001", "start_index": 1, "end_index": 2, "title": "Intro"},
            {"node_id": "0002", "start_index": 3, "end_index": 4, "title": "Body"},
        ]

        choose_relevant_nodes(
            structure,
            "What changed?",
            "openai/test-model",
            top_k=12,
        )

        prompt = mock_completion.call_args.kwargs["prompt"]
        self.assertIn("between 1 and 12 node_ids", prompt)
        self.assertNotIn("1 to 5 node_ids", prompt)

    @patch("app.services.pageindex_service.llm_completion")
    def test_choose_relevant_nodes_populates_outline_diagnostics(self, mock_completion):
        mock_completion.return_value = "{\"node_ids\": [\"0001\"], \"why\": \"specific\"}"

        structure = [
            {"node_id": "0001", "start_index": 1, "end_index": 2, "title": "Intro"},
            {"node_id": "0002", "start_index": 3, "end_index": 4, "title": "Body"},
        ]
        diagnostics: dict[str, object] = {}

        choose_relevant_nodes(
            structure,
            "What changed?",
            "openai/test-model",
            top_k=2,
            diagnostics=diagnostics,
        )

        self.assertEqual(diagnostics["requested_top_k"], 2)
        self.assertEqual(diagnostics["available_node_count"], 2)
        self.assertEqual(diagnostics["selected_count"], 1)
        self.assertEqual(diagnostics["selected_node_ids"], ["0001"])
        self.assertEqual(diagnostics["outline_selection_strategy"], "outline_llm")

        snapshot = snapshot_outline_diagnostics(
            {
                "document_id": "doc_1",
                "version_id": "ver_1",
                "document_label": "manual-a.pdf",
                "version_label": "v1",
            },
            diagnostics,
            candidate_count=1,
        )

        self.assertEqual(snapshot["document_id"], "doc_1")
        self.assertEqual(snapshot["candidate_count"], 1)
        self.assertEqual(snapshot["requested_top_k"], 2)
        self.assertEqual(snapshot["selected_node_ids"], ["0001"])
        self.assertEqual(snapshot["selection_strategy"], "outline_llm")

    def test_round_robin_merge_preserves_later_manual_candidates(self):
        per_manual_candidates = [
            [{"candidate_id": "a1"}, {"candidate_id": "a2"}],
            [{"candidate_id": "b1"}, {"candidate_id": "b2"}],
            [{"candidate_id": "c1"}],
        ]

        merged = merge_candidates_round_robin(per_manual_candidates, 5)

        self.assertEqual(
            [candidate["candidate_id"] for candidate in merged],
            ["a1", "b1", "c1", "a2", "b2"],
        )

    @patch("app.services.pageindex_service.get_text_of_pdf_pages_with_labels")
    @patch("app.services.pageindex_service.get_page_tokens")
    def test_build_answer_context_skips_oversize_first_section(self, mock_get_page_tokens, mock_get_text):
        mock_get_page_tokens.return_value = [("page-1", 6), ("page-2", 2)]
        mock_get_text.side_effect = lambda pdf_pages, start, end: f"section-{start}-{end}"

        context = build_answer_context(
            [
                {"title": "Too big", "start_index": 1, "end_index": 1},
                {"title": "Fits", "start_index": 2, "end_index": 2},
            ],
            "/tmp/demo.pdf",
            "openai/test-model",
            max_context_tokens=5,
        )

        self.assertEqual(context, "## Section: Fits (pages 2-2)\nsection-2-2")
        mock_get_text.assert_called_once()

    def test_load_structure_file_reuses_same_json_artifact_within_run(self):
        backend = _RecordingArtifactBackend(
            json_payload={
                "structure": [
                    {"node_id": "0001", "start_index": 1, "end_index": 2, "title": "Intro"},
                    {"node_id": "0002", "start_index": 3, "end_index": 4, "title": "Body"},
                ]
            }
        )

        with patch("app.services.storage_service._get_storage_backend", return_value=backend):
            with run_reuse_scope():
                first = load_structure_file("minio://bucket/tenant/doc/version/structure.json")
                second = load_structure_file("minio://bucket/tenant/doc/version/structure.json")

        self.assertEqual(backend.read_json_calls, 1)
        self.assertEqual(first, second)
        self.assertEqual([node["node_id"] for node in first], ["0001", "0002"])

    @patch("pageindex.utils.litellm.token_counter", side_effect=lambda model, text: len(text.split()))
    @patch("pageindex.utils.PyPDF2.PdfReader")
    def test_build_answer_context_reuses_page_tokenization_within_run(self, mock_pdf_reader, _mock_token_counter):
        class FakePage:
            def __init__(self, text: str) -> None:
                self._text = text

            def extract_text(self) -> str:
                return self._text

        class FakePdfReader:
            def __init__(self, pdf_path):
                self.pages = [FakePage("alpha"), FakePage("beta")]

        mock_pdf_reader.side_effect = lambda pdf_path: FakePdfReader(pdf_path)

        with run_reuse_scope():
            first = build_answer_context(
                [{"title": "Intro", "start_index": 1, "end_index": 1}],
                "/tmp/shared.pdf",
                "openai/test-model",
            )
            second = build_answer_context(
                [{"title": "Body", "start_index": 2, "end_index": 2}],
                "/tmp/shared.pdf",
                "openai/test-model",
            )

        self.assertEqual(mock_pdf_reader.call_count, 1)
        self.assertIn("## Section: Intro (pages 1-1)", first)
        self.assertIn("## Section: Body (pages 2-2)", second)

    @patch("pageindex.utils.litellm.token_counter", side_effect=lambda model, text: len(text.split()))
    @patch("pageindex.utils.PyPDF2.PdfReader")
    def test_build_context_from_citations_uses_section_text_provider_without_pdf(self, mock_pdf_reader, _mock_token_counter):
        class FakeProvider:
            def get_for_citations(self, citations):
                return [
                    SectionTextResult(
                        text="alpha section",
                        source="es_shadow",
                        status="ready",
                        node_id=citation.get("node_id"),
                        page_start=citation.get("page_start"),
                        page_end=citation.get("page_end"),
                        title=citation.get("title"),
                    )
                    for citation in citations
                ]

        blocks = asyncio.run(
            build_context_from_citations_async(
                [
                    {
                        "citation_id": "cit_1",
                        "document_id": "doc_1",
                        "version_id": "ver_1",
                        "node_id": "n1",
                        "document_label": "manual-a.pdf",
                        "page_start": 1,
                        "page_end": 1,
                        "title": "Intro",
                    }
                ],
                model="openai/test-model",
                max_context_pages=None,
                max_context_tokens=None,
                section_text_provider=FakeProvider(),
            )
        )

        self.assertEqual(mock_pdf_reader.call_count, 0)
        self.assertEqual(len(blocks), 1)
        self.assertIn("alpha section", blocks[0])

    @patch("app.services.pageindex_service.get_page_tokens", side_effect=AssertionError("runtime PDF extraction should not run"))
    def test_build_context_from_citations_missing_text_default_does_not_extract_pdf(self, _mock_get_page_tokens):
        class FakeProvider:
            def get_for_citations(self, citations):
                return [
                    SectionTextResult(
                        text=None,
                        source="missing",
                        status="missing",
                        degraded_reason="es_index_missing",
                    )
                    for _citation in citations
                ]

        blocks = asyncio.run(
            build_context_from_citations_async(
                [
                    {
                        "citation_id": "cit_1",
                        "document_id": "doc_1",
                        "version_id": "ver_1",
                        "node_id": "n1",
                        "page_start": 1,
                        "page_end": 1,
                        "_storage_path": "/tmp/source.pdf",
                    }
                ],
                model="openai/test-model",
                max_context_pages=None,
                max_context_tokens=None,
                section_text_provider=FakeProvider(),
            )
        )

        self.assertEqual(blocks, [])

    @patch("app.services.pageindex_service.get_page_tokens", side_effect=AssertionError("runtime PDF extraction should not run"))
    def test_build_context_from_citations_stale_text_is_not_used(self, _mock_get_page_tokens):
        class FakeProvider:
            def get_for_citations(self, citations):
                return [
                    SectionTextResult(
                        text="stale section",
                        source="stale",
                        status="stale",
                        stale=True,
                        degraded_reason="routing_index_version_mismatch",
                    )
                    for _citation in citations
                ]

        blocks = asyncio.run(
            build_context_from_citations_async(
                [
                    {
                        "citation_id": "cit_1",
                        "document_id": "doc_1",
                        "version_id": "ver_1",
                        "node_id": "n1",
                        "page_start": 1,
                        "page_end": 1,
                        "_storage_path": "/tmp/source.pdf",
                    }
                ],
                model="openai/test-model",
                max_context_pages=None,
                max_context_tokens=None,
                section_text_provider=FakeProvider(),
            )
        )

        self.assertEqual(blocks, [])

    def test_section_text_provider_reads_page_span_from_es_and_marks_stale(self):
        class FakeIndices:
            def exists(self, index):
                return True

        class FakeEs:
            indices = FakeIndices()

            def search(self, index, body):
                return {
                    "hits": {
                        "hits": [
                            {
                                "_id": "doc_1:ver_1:n1",
                                "_source": {
                                    "document_id": "doc_1",
                                    "version_id": "ver_1",
                                    "node_id": "n1",
                                    "node_key": "doc_1:ver_1:n1",
                                    "title": "Intro",
                                    "page_start": 1,
                                    "page_end": 2,
                                    "section_text": "ES section text",
                                    "section_text_checksum": "checksum-1",
                                    "routing_index_version": "v1",
                                },
                            }
                        ]
                    }
                }

        settings = MagicMock()
        settings.routing_node_es_enabled = True
        settings.routing_node_es_index_prefix = "pageindex-node-embeddings"
        provider = SectionTextProvider(
            settings_obj=settings,
            embedding_config={"enabled": True, "provider_type": "test", "model": "m"},
            es_client=FakeEs(),
        )

        ready = provider.get_by_page_span(
            document_id="doc_1",
            version_id="ver_1",
            page_start=1,
            page_end=2,
            routing_index_version="v1",
        )
        stale = provider.get_by_page_span(
            document_id="doc_1",
            version_id="ver_1",
            page_start=1,
            page_end=2,
            routing_index_version="v2",
        )

        self.assertEqual(ready.status, "ready")
        self.assertEqual(ready.text, "ES section text")
        self.assertEqual(ready.source, "es_shadow")
        self.assertTrue(stale.stale)
        self.assertEqual(stale.status, "stale")
        self.assertEqual(stale.source, "stale")
        self.assertEqual(stale.degraded_reason, "routing_index_version_mismatch")

    @patch("pageindex.utils.litellm.token_counter", side_effect=lambda model, text: len(text.split()))
    @patch("pageindex.utils.PyPDF2.PdfReader")
    def test_build_context_from_citations_debug_pdf_fallback_reuses_shared_storage_path(self, mock_pdf_reader, _mock_token_counter):
        class FakePage:
            def __init__(self, text: str) -> None:
                self._text = text

            def extract_text(self) -> str:
                return self._text

        class FakePdfReader:
            def __init__(self, pdf_path):
                self.pages = [FakePage("alpha"), FakePage("beta")]

        from app.services.storage_service import MinioArtifactStorage

        class FakeMinioClient:
            def __init__(self) -> None:
                self.fget_calls = 0
                self._lock = threading.Lock()

            def fget_object(self, bucket, key, target_path):
                with self._lock:
                    self.fget_calls += 1
                Path(target_path).write_text("fake pdf", encoding="utf-8")

        backend = object.__new__(MinioArtifactStorage)
        backend.client = FakeMinioClient()
        backend._parse_uri = lambda uri: ("bucket", "tenant/doc/version/source.pdf")
        mock_pdf_reader.side_effect = lambda pdf_path: FakePdfReader(pdf_path)

        citations = [
            {
                "citation_id": "cit_1",
                "candidate_id": "cand_1",
                "document_id": "doc_1",
                "document_label": "manual-a.pdf",
                "page_start": 1,
                "page_end": 1,
                "title": "Intro",
                "_node": {"title": "Intro", "start_index": 1, "end_index": 1},
                "_storage_path": "minio://bucket/tenant/doc/version/source.pdf",
            },
            {
                "citation_id": "cit_2",
                "candidate_id": "cand_2",
                "document_id": "doc_1",
                "document_label": "manual-a.pdf",
                "page_start": 2,
                "page_end": 2,
                "title": "Body",
                "_node": {"title": "Body", "start_index": 2, "end_index": 2},
                "_storage_path": "minio://bucket/tenant/doc/version/source.pdf",
            },
        ]

        with patch("app.services.storage_service._get_storage_backend", return_value=backend):
            with run_reuse_scope():
                blocks = asyncio.run(
                    build_context_from_citations_async(
                        citations,
                        model="openai/test-model",
                        max_context_pages=None,
                        max_context_tokens=None,
                        allow_runtime_pdf_fallback=True,
                    )
                )

        self.assertEqual(backend.client.fget_calls, 1)
        self.assertEqual(mock_pdf_reader.call_count, 1)
        self.assertEqual(len(blocks), 2)
        self.assertIn("[cit_1]", blocks[0])
        self.assertIn("[cit_2]", blocks[1])

    def test_local_artifact_path_keeps_local_paths_unchanged(self):
        from app.services.storage_service import local_artifact_path

        with patch("app.services.storage_service._get_storage_backend", return_value=_LocalPassthroughBackend()):
            with local_artifact_path("/tmp/local-document.pdf") as resolved_path:
                self.assertEqual(resolved_path, Path("/tmp/local-document.pdf"))


if __name__ == "__main__":
    unittest.main()
