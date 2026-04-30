import asyncio
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.principal import Principal
from app.services import chat_service


class TrackingSession:
    def __init__(self, tracker):
        self.tracker = tracker

    def __enter__(self):
        self.tracker["opened"] += 1
        self.tracker["active"] += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.tracker["closed"] += 1
        self.tracker["active"] -= 1


class FakeSubscription:
    def __init__(self, tracker):
        self.tracker = tracker
        self.closed = False

    async def next_event(self, timeout=None):
        self.tracker["active_during_wait"] = self.tracker["active"]
        return {"event": "status", "data": {"status": "cancelled"}}

    async def close(self):
        self.closed = True


class TestStreamingSessionLifecycle(unittest.TestCase):
    def test_stream_releases_create_session_before_waiting_on_subscription(self):
        tracker = {"opened": 0, "closed": 0, "active": 0, "active_during_wait": None}
        user = SimpleNamespace(id="user_1", tenant_id="tenant_1")
        principal = Principal(
            kind="session",
            tenant_id="tenant_1",
            workspace_id="ws_1",
            tenant_membership_role="admin",
            tenant_membership_status="active",
            workspace_membership_role="admin",
            workspace_membership_status="active",
            workspace_permissions={"can_run_skills": True},
            user=user,
        )
        skill = SimpleNamespace(id="skill_1", workspace_id="ws_1", provider_id=None, model="model")
        document = SimpleNamespace(id="doc_1", workspace_id="ws_1", display_name="Doc", source_filename="doc.pdf")
        version = SimpleNamespace(
            id="ver_1",
            version_no=1,
            parsed_structure_path="/tmp/structure.json",
            parse_status="index_ready",
        )
        run = SimpleNamespace(
            id="run_1",
            tenant_id="tenant_1",
            session_id=None,
            created_at=datetime(2026, 4, 29, 10, 0, 0),
        )
        subscription = FakeSubscription(tracker)

        def session_factory():
            return TrackingSession(tracker)

        async def scenario():
            stream = chat_service.stream_skill_run_events(
                session_factory=session_factory,
                principal=principal,
                user=user,
                skill=skill,
                document=document,
                version=version,
                question="hello",
                model="model",
                request_config={"_run_target": {"manuals": []}},
                conversation_config={},
                retrieval_config={},
                generation_config={},
            )
            events = [await anext(stream), await anext(stream), await anext(stream), await anext(stream)]
            await stream.aclose()
            return events

        with (
            patch.object(chat_service, "_create_pending_run", return_value=run),
            patch.object(chat_service, "_record_chat_observation", new=AsyncMock()),
            patch.object(chat_service, "_mark_run_queued", return_value=run),
            patch.object(chat_service, "open_chat_event_subscription", new=AsyncMock(return_value=subscription)),
        ):
            events = asyncio.run(scenario())

        self.assertEqual([event["event"] for event in events], ["run_started", "status", "status", "status"])
        self.assertEqual(tracker["active_during_wait"], 0)
        self.assertEqual(tracker["active"], 0)
        self.assertEqual(tracker["opened"], tracker["closed"])
        self.assertTrue(subscription.closed)


if __name__ == "__main__":
    unittest.main()
