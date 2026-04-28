import asyncio
from contextlib import ExitStack
import importlib.util
import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.modules.setdefault("jwt", MagicMock())
sys.modules.setdefault("litellm", MagicMock())
sys.modules.setdefault("PyPDF2", MagicMock())
sys.modules.setdefault("pymupdf", MagicMock())
sys.modules.setdefault("dotenv", MagicMock())
sys.modules.setdefault("yaml", MagicMock())
sys.modules.setdefault("redis", MagicMock())

from app.core.principal import Principal
from app.core.db import Base
from app.models import ChatRun, ChatSkill, Document, DocumentVersion, Tenant, User, Workspace
from app.services.chat_service import (
    CHAT_RETRIEVAL_MODE_DEEP_RESEARCH,
    CHAT_RETRIEVAL_MODE_FAST,
    _build_execution_context,
    _load_session_history,
    _validate_execution_options,
    run_chat_run,
    stream_skill_run_events,
)


CHAT_ROUTER_MODULE_NAME = "phase48_chat_router_under_test"
CHAT_ROUTER_PATH = Path(__file__).resolve().parents[2] / "app" / "api" / "routers" / "chat.py"


class TestSkillStreamRuntimeContract(unittest.TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id="user_1", tenant_id="tenant_1")
        self.principal = Principal(
            kind="session",
            tenant_id="tenant_1",
            workspace_id="ws_1",
            tenant_membership_role="admin",
            tenant_membership_status="active",
            workspace_membership_role="admin",
            workspace_membership_status="active",
            workspace_permissions={"can_run_skills": True, "can_view_runs": True},
            user=self.user,
        )
        self.skill = SimpleNamespace(
            id="skill_1",
            name="Demo Skill",
            model="openai/saved-model",
            request_config_json="{}",
            conversation_config_json="{}",
            retrieval_config_json="{}",
            generation_config_json="{}",
            documents=[SimpleNamespace(document_id="doc_1")],
        )
        self.document = SimpleNamespace(id="doc_1", workspace_id="ws_1")
        self.version = SimpleNamespace(id="ver_1", parsed_structure_path="/tmp/parsed.json", parse_status="index_ready")

    @patch("app.services.chat_service._create_pending_run")
    def test_stream_skill_run_events_accepts_explicit_model(self, mock_create_pending_run):
        created_run = SimpleNamespace(
            id="run_1",
            tenant_id="tenant_1",
            session_id="session_1",
            created_at=datetime(2026, 4, 21, 10, 0, 0),
        )
        mock_create_pending_run.return_value = created_run

        async def scenario():
            stream = stream_skill_run_events(
                MagicMock(),
                principal=self.principal,
                user=self.user,
                skill=self.skill,
                document=self.document,
                version=self.version,
                question="hello",
                model="openai/draft-model",
                request_config={},
                conversation_config={},
                retrieval_config={},
                generation_config={},
            )
            return await anext(stream)

        first_event = asyncio.run(scenario())

        self.assertEqual(first_event["event"], "run_started")
        _, kwargs = mock_create_pending_run.call_args
        self.assertEqual(kwargs["model"], "openai/draft-model")

    def test_retrieval_mode_defaults_to_deep_research(self):
        _, retrieval_config, _ = _validate_execution_options({}, {}, {})

        self.assertEqual(retrieval_config["retrieval_mode"], CHAT_RETRIEVAL_MODE_DEEP_RESEARCH)
        self.assertNotIn("node_top_k", retrieval_config)

    def test_retrieval_mode_fast_normalizes_node_top_k(self):
        _, retrieval_config, _ = _validate_execution_options(
            {},
            {"retrieval_mode": "fast"},
            {},
        )

        self.assertEqual(retrieval_config["retrieval_mode"], CHAT_RETRIEVAL_MODE_FAST)
        self.assertEqual(retrieval_config["node_top_k"], 3)

    @patch("app.services.chat_service._create_pending_run")
    def test_stream_skill_run_events_accepts_fast_retrieval_mode(self, mock_create_pending_run):
        created_run = SimpleNamespace(
            id="run_fast",
            tenant_id="tenant_1",
            session_id="session_1",
            created_at=datetime(2026, 4, 21, 10, 0, 0),
        )
        mock_create_pending_run.return_value = created_run

        async def scenario():
            stream = stream_skill_run_events(
                MagicMock(),
                principal=self.principal,
                user=self.user,
                skill=self.skill,
                document=self.document,
                version=self.version,
                question="hello",
                model="openai/draft-model",
                request_config={},
                conversation_config={},
                retrieval_config={"retrieval_mode": "fast", "node_top_k": 10},
                generation_config={},
            )
            return await anext(stream)

        first_event = asyncio.run(scenario())

        self.assertEqual(first_event["event"], "run_started")
        _, kwargs = mock_create_pending_run.call_args
        self.assertEqual(kwargs["retrieval_config"]["retrieval_mode"], "fast")
        self.assertEqual(kwargs["retrieval_config"]["node_top_k"], 10)

    @patch("app.services.chat_service.count_tokens", side_effect=lambda text, model: len(str(text).split()))
    @patch("app.services.chat_service.list_session_messages")
    def test_history_context_only_uses_user_and_final_assistant_messages(self, mock_list_session_messages, _mock_count_tokens):
        mock_list_session_messages.return_value = [
            SimpleNamespace(id="m1", role="user", content="previous question", sequence_no=1, run_id="run_1"),
            SimpleNamespace(id="m2", role="tool", content="retrieval trace should not enter prompt", sequence_no=2, run_id="run_1"),
            SimpleNamespace(id="m3", role="assistant", content="final answer only", sequence_no=3, run_id="run_1"),
            SimpleNamespace(id="m4", role="user", content="current question", sequence_no=4, run_id="run_2"),
        ]

        messages, info = _load_session_history(
            MagicMock(),
            tenant_id="tenant_1",
            workspace_id="ws_1",
            session_id="session_1",
            model="openai/test-model",
            conversation_config={
                "include_history": True,
                "include_assistant_messages": True,
                "history_turn_limit": 4,
                "history_token_budget": 1000,
            },
            current_question="current question",
        )

        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual([message["content"] for message in messages], ["previous question", "final answer only"])
        self.assertTrue(info["used"])

    def test_stream_route_emits_error_event_when_stream_setup_fails(self):
        chat_router_spec = importlib.util.spec_from_file_location(CHAT_ROUTER_MODULE_NAME, CHAT_ROUTER_PATH)
        chat_router_module = importlib.util.module_from_spec(chat_router_spec)
        assert chat_router_spec is not None and chat_router_spec.loader is not None
        sys.modules[CHAT_ROUTER_MODULE_NAME] = chat_router_module
        chat_router_spec.loader.exec_module(chat_router_module)

        app = FastAPI()
        app.include_router(chat_router_module.router)
        app.dependency_overrides[chat_router_module.get_current_principal] = lambda: self.principal
        app.dependency_overrides[chat_router_module.get_db] = lambda: MagicMock()
        chat_router_module._require_can_run_skills = lambda principal: None
        chat_router_module.get_skill_or_404 = lambda db, principal, skill_id: self.skill
        chat_router_module.resolve_document_version = lambda db, principal, document_id, version_id: (self.document, self.version)

        async def broken_stream_skill_run_events(*args, **kwargs):
            if False:
                yield None
            raise RuntimeError("boom-before-run")

        chat_router_module.stream_skill_run_events = broken_stream_skill_run_events

        client = TestClient(app, raise_server_exceptions=False)
        with client.stream(
            "POST",
            "/api/v1/chat/skills/skill_1/run",
            json={"question": "hello", "stream": True},
        ) as response:
            body = b"".join(response.iter_raw()).decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: error", body)
        self.assertIn("boom-before-run", body)

    def test_build_execution_context_preserves_retrieval_diagnostics(self):
        execution_context = _build_execution_context(
            provider_config={
                "provider_id": "provider_1",
                "name": "Provider",
                "provider_type": "openai",
                "scope": "workspace",
                "resolution_source": "workspace",
            },
            resolved_model="openai/test-model",
            conversation_config={},
            history_info={
                "used": False,
                "history_messages_used": 0,
                "history_turns_used": 0,
                "history_token_estimate": 0,
            },
            retrieval_info={
                "diagnostics": {
                    "manual_gate": {
                        "decision": "fallback_full",
                        "shadow_eval": {
                            "top1_hit_final_citation_manuals": False,
                        },
                    },
                    "outline": {
                        "manuals": [
                            {
                                "document_id": "doc_1",
                                "selected_node_ids": ["0001"],
                            }
                        ],
                    },
                    "rerank": {
                        "meta": {"applied": False, "mode": "round_robin_manual_merge"},
                        "repair": {},
                    },
                },
                "outline_selection_strategy": "outline_llm",
                "documents_considered": 1,
            },
            generation_info={"temperature": 0},
        )

        self.assertEqual(
            execution_context["retrieval"]["diagnostics"]["outline"]["manuals"][0]["selected_node_ids"],
            ["0001"],
        )
        self.assertEqual(
            execution_context["retrieval"]["diagnostics"]["manual_gate"]["decision"],
            "fallback_full",
        )
        self.assertFalse(execution_context["retrieval"]["diagnostics"]["rerank"]["meta"]["applied"])

    def _create_fast_run_session(self, run_id: str):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

        with SessionLocal() as db:
            db.add(Tenant(id="tenant_1", name="Tenant"))
            db.add(
                User(
                    id="user_1",
                    tenant_id="tenant_1",
                    username="user_1",
                    email="user@example.com",
                    password_hash="hash",
                )
            )
            db.commit()
            db.add(Workspace(id="ws_1", tenant_id="tenant_1", name="Workspace", slug="ws", created_by="user_1"))
            db.add(
                Document(
                    id="doc_1",
                    tenant_id="tenant_1",
                    workspace_id="ws_1",
                    owner_user_id="user_1",
                    display_name="Manual",
                    source_filename="manual.pdf",
                    active_version_id=None,
                    status="index_ready",
                )
            )
            db.commit()
            db.add(
                DocumentVersion(
                    id="ver_1",
                    document_id="doc_1",
                    version_no=1,
                    storage_path="/tmp/manual.pdf",
                    file_hash="hash",
                    parse_status="index_ready",
                    parsed_structure_path="/tmp/structure.json",
                    routing_index_status="index_ready",
                    routing_index_path="/tmp/routing.json",
                    routing_index_version="v1",
                )
            )
            db.commit()
            document = db.get(Document, "doc_1")
            document.active_version_id = "ver_1"
            db.add(
                ChatSkill(
                    id="skill_1",
                    tenant_id="tenant_1",
                    workspace_id="ws_1",
                    owner_user_id="user_1",
                    name="Fast Skill",
                    description=None,
                    system_prompt="Use the provided source.",
                    provider_id=None,
                    model="openai/test-model",
                    request_config_json="{}",
                    conversation_config_json="{}",
                    retrieval_config_json="{}",
                    generation_config_json="{}",
                    visibility="workspace_edit",
                )
            )
            db.add(
                ChatRun(
                    id=run_id,
                    tenant_id="tenant_1",
                    workspace_id="ws_1",
                    user_id="user_1",
                    session_id=None,
                    document_id="doc_1",
                    version_id="ver_1",
                    skill_id="skill_1",
                    provider_id=None,
                    model="openai/test-model",
                    question="Which node applies?",
                    status="queued",
                    cancel_requested=False,
                    request_config_json="{}",
                    conversation_config_json=json.dumps({}),
                    retrieval_config_json=json.dumps({"retrieval_mode": "fast", "node_top_k": 5}),
                    generation_config_json=json.dumps({"temperature": 0}),
                    selected_sections_json="[]",
                    citations_json="[]",
                    execution_context_json="{}",
                    metrics_json="{}",
                    last_error=None,
                )
            )
            db.commit()
        return SessionLocal

    def _fast_retrieval_result(self) -> dict:
        return {
            "mode": "sparse_only",
            "node_top_k": 5,
            "node_search_latency_ms": 4,
            "node_shadow_latency_ms": 3,
            "selected_nodes": [
                {
                    "document_id": "doc_1",
                    "version_id": "ver_1",
                    "node_id": "0195",
                    "title": "11.2 旅客运输标准和要求",
                    "page_start": 933,
                    "page_end": 950,
                    "hybrid_score": 0.9,
                    "corpus_source": "document_routing_nodes",
                }
            ],
            "selected_node_count": 1,
            "content_backed_node_count": 1,
            "citations_with_internal": [
                {
                    "citation_id": "cit_1",
                    "document_id": "doc_1",
                    "version_id": "ver_1",
                    "node_id": "0195",
                    "title": "11.2 旅客运输标准和要求",
                    "page_start": 933,
                    "page_end": 950,
                    "source": "document_routing_nodes",
                    "_node": {"node_id": "0195", "title": "11.2 旅客运输标准和要求", "start_index": 933, "end_index": 950},
                    "_storage_path": "/tmp/manual.pdf",
                }
            ],
            "boundary_flags": [],
            "fallback_recommendation": None,
            "active_backend": "lexical_fallback",
            "fallback_reason": "embedding_build_mode_disabled",
            "requested_dense_source": "es_shadow",
            "dense_source": "sparse",
            "dense": {"resolved_mode": "sparse_only", "fallback_reason": "embedding_build_mode_disabled"},
            "corpus_summary": {"manual_count": 1, "node_count": 1},
            "documents_considered": 1,
            "documents_with_hits": 1,
        }

    def _chunk(self, delta: str, *, usage: dict | None = None, finish_reason: str | None = None):
        return SimpleNamespace(
            usage=usage,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=delta),
                    finish_reason=finish_reason,
                )
            ],
        )

    def _delta_chunks(self, count: int):
        chunks = []
        for index in range(count):
            chunks.append(
                self._chunk(
                    f"delta-{index} ",
                    usage={"prompt_tokens": 7, "completion_tokens": count, "total_tokens": count + 7}
                    if index == count - 1
                    else None,
                    finish_reason="stop" if index == count - 1 else None,
                )
            )
        return chunks

    def _run_fast_case(
        self,
        *,
        run_id: str,
        chunks: list,
        publish_side_effect=None,
        interval_side_effect=None,
    ):
        SessionLocal = self._create_fast_run_session(run_id)
        events: list[tuple[str, dict]] = []
        observations: list[dict] = []

        async def record_observation(run, *, event_type: str, step=None, status_value=None, payload=None):
            observations.append(
                {
                    "event_type": event_type,
                    "step": step,
                    "status_value": status_value,
                    "payload": payload or {},
                }
            )

        async def publish_event(_run_id: str, event: str, data: dict):
            events.append((event, data))
            if publish_side_effect:
                await publish_side_effect(SessionLocal, _run_id, event, data)

        async def close_stream(_run_id: str):
            return None

        with ExitStack() as stack:
            stack.enter_context(patch("app.services.chat_service.SessionLocal", SessionLocal))
            stack.enter_context(
                patch(
                    "app.services.chat_service.resolve_provider_config",
                    return_value={
                        "provider_id": "provider_1",
                        "name": "Provider",
                        "provider_type": "openai",
                        "scope": "workspace",
                        "resolution_source": "test",
                        "base_url": "http://provider.test",
                        "api_key": "key",
                        "extra_headers": {},
                        "default_model": "openai/test-model",
                        "supported_models": ["openai/test-model"],
                    },
                )
            )
            stack.enter_context(patch("app.services.chat_service.validate_provider_model_selection", return_value="openai/test-model"))
            stack.enter_context(patch("app.services.chat_service.resolve_embedding_config", return_value={"enabled": False, "resolved_mode": "sparse_only"}))
            stack.enter_context(patch("app.services.chat_service._record_chat_observation", side_effect=record_observation))
            stack.enter_context(patch("app.services.chat_service._publish_chat_event", side_effect=publish_event))
            stack.enter_context(patch("app.services.chat_service.close_chat_event_stream", side_effect=close_stream))
            stack.enter_context(patch("app.services.chat_service._run_fast_node_retrieval", return_value=self._fast_retrieval_result()))
            stack.enter_context(
                patch(
                    "app.services.chat_service.build_context_from_citations_async",
                    return_value=["<physical_index_938>无成人陪伴儿童：10个。</physical_index_938>"],
                )
            )
            stack.enter_context(patch("app.services.chat_service.litellm.completion", return_value=chunks))
            if interval_side_effect:
                stack.enter_context(patch("app.services.chat_service._chat_stream_interval_seconds", side_effect=interval_side_effect))

            asyncio.run(run_chat_run(run_id))

        with SessionLocal() as db:
            stored = db.get(ChatRun, run_id)
            snapshot = SimpleNamespace(
                status=stored.status,
                answer_text=stored.answer_text,
                last_error=stored.last_error,
                cancel_requested=stored.cancel_requested,
                metrics=json.loads(stored.metrics_json),
            )
        return snapshot, events, observations

    def test_final_answer_stream_throttles_heartbeat_for_many_deltas(self):
        snapshot, events, _observations = self._run_fast_case(
            run_id="run_hot_path_heartbeats",
            chunks=self._delta_chunks(300),
        )

        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.metrics["streamed_delta_count"], 300)
        self.assertLess(snapshot.metrics["heartbeat_count"], 300)
        self.assertLess(snapshot.metrics["cancel_check_count"], 300)
        self.assertEqual(len([event for event, _data in events if event == "answer_delta"]), 300)

    def test_final_answer_stream_does_not_observe_every_delta(self):
        snapshot, _events, observations = self._run_fast_case(
            run_id="run_hot_path_observations",
            chunks=self._delta_chunks(300),
        )

        answer_delta_observations = [
            observation for observation in observations if observation["event_type"] == "answer_delta"
        ]
        self.assertEqual(snapshot.status, "completed")
        self.assertEqual(snapshot.metrics["streamed_delta_count"], 300)
        self.assertEqual(snapshot.metrics["answer_delta_observation_count"], 1)
        self.assertEqual(len(answer_delta_observations), 1)

    def test_final_answer_stream_cancel_check_still_honors_cancel_request(self):
        async def cancel_after_third_delta(SessionLocal, run_id: str, event: str, data: dict):
            if event != "answer_delta" or data.get("seq") != 3:
                return
            with SessionLocal() as db:
                run = db.get(ChatRun, run_id)
                run.cancel_requested = True
                run.cancel_reason = "test cancel"
                db.commit()
            await asyncio.sleep(0.01)

        def interval_override(name: str, default: float, *, minimum: float) -> float:
            if "cancel_check" in name:
                return 0.001
            return 60.0

        snapshot, events, _observations = self._run_fast_case(
            run_id="run_hot_path_cancel",
            chunks=self._delta_chunks(50),
            publish_side_effect=cancel_after_third_delta,
            interval_side_effect=interval_override,
        )

        streamed = [event for event, _data in events if event == "answer_delta"]
        self.assertEqual(snapshot.status, "cancelled")
        self.assertTrue(snapshot.cancel_requested)
        self.assertEqual(snapshot.last_error, "test cancel")
        self.assertLess(len(streamed), 50)

    def test_fast_mode_run_generates_answer_and_persists_artifacts(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

        with SessionLocal() as db:
            db.add(Tenant(id="tenant_1", name="Tenant"))
            db.add(
                User(
                    id="user_1",
                    tenant_id="tenant_1",
                    username="user_1",
                    email="user@example.com",
                    password_hash="hash",
                )
            )
            db.commit()
            db.add(Workspace(id="ws_1", tenant_id="tenant_1", name="Workspace", slug="ws", created_by="user_1"))
            db.add(
                Document(
                    id="doc_1",
                    tenant_id="tenant_1",
                    workspace_id="ws_1",
                    owner_user_id="user_1",
                    display_name="Manual",
                    source_filename="manual.pdf",
                    active_version_id=None,
                    status="index_ready",
                )
            )
            db.commit()
            db.add(
                DocumentVersion(
                    id="ver_1",
                    document_id="doc_1",
                    version_no=1,
                    storage_path="/tmp/manual.pdf",
                    file_hash="hash",
                    parse_status="index_ready",
                    parsed_structure_path="/tmp/structure.json",
                    routing_index_status="index_ready",
                    routing_index_path="/tmp/routing.json",
                    routing_index_version="v1",
                )
            )
            db.commit()
            document = db.get(Document, "doc_1")
            document.active_version_id = "ver_1"
            db.add(
                ChatSkill(
                    id="skill_1",
                    tenant_id="tenant_1",
                    workspace_id="ws_1",
                    owner_user_id="user_1",
                    name="Fast Skill",
                    description=None,
                    system_prompt="Use the provided source.",
                    provider_id=None,
                    model="openai/test-model",
                    request_config_json="{}",
                    conversation_config_json="{}",
                    retrieval_config_json="{}",
                    generation_config_json="{}",
                    visibility="workspace_edit",
                )
            )
            db.add(
                ChatRun(
                    id="run_fast",
                    tenant_id="tenant_1",
                    workspace_id="ws_1",
                    user_id="user_1",
                    session_id=None,
                    document_id="doc_1",
                    version_id="ver_1",
                    skill_id="skill_1",
                    provider_id=None,
                    model="openai/test-model",
                    question="Which node applies?",
                    status="queued",
                    cancel_requested=False,
                    request_config_json="{}",
                    conversation_config_json=json.dumps({}),
                    retrieval_config_json=json.dumps({"retrieval_mode": "fast", "node_top_k": 5}),
                    generation_config_json=json.dumps({"temperature": 0}),
                    selected_sections_json="[]",
                    citations_json="[]",
                    execution_context_json="{}",
                    metrics_json="{}",
                    last_error=None,
                )
            )
            db.commit()

        events: list[tuple[str, dict]] = []

        async def no_observation(*args, **kwargs):
            return None

        async def publish_event(_run_id: str, event: str, data: dict):
            events.append((event, data))

        async def close_stream(_run_id: str):
            return None

        fast_retrieval = {
            "mode": "sparse_only",
            "node_top_k": 5,
            "node_search_latency_ms": 4,
            "node_shadow_latency_ms": 3,
            "selected_nodes": [
                {
                    "document_id": "doc_1",
                    "version_id": "ver_1",
                    "node_id": "0195",
                    "title": "11.2 旅客运输标准和要求",
                    "page_start": 933,
                    "page_end": 950,
                    "hybrid_score": 0.9,
                    "corpus_source": "document_routing_nodes",
                }
            ],
            "selected_node_count": 1,
            "content_backed_node_count": 1,
            "citations_with_internal": [
                {
                    "citation_id": "cit_1",
                    "document_id": "doc_1",
                    "version_id": "ver_1",
                    "node_id": "0195",
                    "title": "11.2 旅客运输标准和要求",
                    "page_start": 933,
                    "page_end": 950,
                    "source": "document_routing_nodes",
                    "_node": {"node_id": "0195", "title": "11.2 旅客运输标准和要求", "start_index": 933, "end_index": 950},
                    "_storage_path": "/tmp/manual.pdf",
                }
            ],
            "boundary_flags": [],
            "fallback_recommendation": None,
            "active_backend": "lexical_fallback",
            "fallback_reason": "embedding_build_mode_disabled",
            "requested_dense_source": "es_shadow",
            "dense_source": "sparse",
            "dense": {"resolved_mode": "sparse_only", "fallback_reason": "embedding_build_mode_disabled"},
            "corpus_summary": {"manual_count": 1, "node_count": 1},
            "documents_considered": 1,
            "documents_with_hits": 1,
        }
        chunk = SimpleNamespace(
            usage={"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content="无成人陪伴儿童最多 10 个；5（含）至 10 岁不得超过 5 个（pages 933-950，page 938）。"
                    ),
                    finish_reason="stop",
                )
            ],
        )

        with patch("app.services.chat_service.SessionLocal", SessionLocal), \
             patch("app.services.chat_service.resolve_provider_config", return_value={
                 "provider_id": "provider_1",
                 "name": "Provider",
                 "provider_type": "openai",
                 "scope": "workspace",
                 "resolution_source": "test",
                 "base_url": "http://provider.test",
                 "api_key": "key",
                 "extra_headers": {},
                 "default_model": "openai/test-model",
                 "supported_models": ["openai/test-model"],
             }), \
             patch("app.services.chat_service.validate_provider_model_selection", return_value="openai/test-model"), \
             patch("app.services.chat_service.resolve_embedding_config", return_value={"enabled": False, "resolved_mode": "sparse_only"}), \
             patch("app.services.chat_service._record_chat_observation", side_effect=no_observation), \
             patch("app.services.chat_service._publish_chat_event", side_effect=publish_event), \
             patch("app.services.chat_service.close_chat_event_stream", side_effect=close_stream), \
             patch("app.services.chat_service._run_fast_node_retrieval", return_value=fast_retrieval), \
             patch(
                 "app.services.chat_service.build_context_from_citations_async",
                 return_value=["<physical_index_938>无成人陪伴儿童：10个，其中5（含）-10岁不得超过5个。</physical_index_938>"],
             ), \
             patch("app.services.chat_service.litellm.completion", return_value=[chunk]):
            asyncio.run(run_chat_run("run_fast"))

        with SessionLocal() as db:
            stored = db.get(ChatRun, "run_fast")
            self.assertEqual(stored.status, "completed")
            self.assertIn("无成人陪伴儿童最多 10 个", stored.answer_text)
            self.assertIn("5（含）至 10 岁不得超过 5 个", stored.answer_text)
            self.assertIn("pages 933-950", stored.answer_text)
            metrics = json.loads(stored.metrics_json)
            execution_context = json.loads(stored.execution_context_json)
            citations = json.loads(stored.citations_json)
            selected_sections = json.loads(stored.selected_sections_json)

        self.assertTrue(any(event == "answer_delta" and "无成人陪伴儿童最多 10 个" in data.get("delta", "") for event, data in events))
        self.assertEqual(metrics["retrieval_mode"], "fast")
        self.assertEqual(metrics["node_top_k"], 5)
        self.assertEqual(metrics["selected_node_count"], 1)
        self.assertEqual(metrics["content_backed_node_count"], 1)
        self.assertEqual(metrics["active_backend"], "lexical_fallback")
        self.assertEqual(metrics["requested_dense_source"], "es_shadow")
        self.assertEqual(metrics["dense_source"], "sparse")
        self.assertEqual(metrics["documents_considered"], 1)
        self.assertEqual(metrics["documents_with_hits"], 1)
        self.assertIn("ttft_ms", metrics)
        self.assertIsInstance(metrics["ttft_ms"], int)
        self.assertEqual(execution_context["retrieval"]["retrieval_mode"], "fast")
        self.assertEqual(execution_context["retrieval"]["node_top_k"], 5)
        self.assertEqual(citations[0]["node_id"], "0195")
        self.assertEqual(citations[0]["page_start"], 933)
        self.assertEqual(citations[0]["page_end"], 950)
        self.assertEqual(citations[0]["source"], "document_routing_nodes")
        self.assertEqual(selected_sections[0]["node_id"], "0195")


if __name__ == "__main__":
    unittest.main()
