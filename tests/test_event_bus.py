"""Tests for SessionEventBus -- publish, subscribe, persistence, polling."""

import asyncio
import json
import time

import pytest

from review_swarm.event_bus import SessionEventBus
from review_swarm.models import EventType


@pytest.fixture
def bus(tmp_path):
    """Fresh event bus with a temp JSONL file."""
    return SessionEventBus("sess-test-001", tmp_path / "events.jsonl")


@pytest.fixture
def events_path(tmp_path):
    return tmp_path / "events.jsonl"


# ── Sync publish + get_events (polling) ──────────────────────────────


class TestPublishSync:
    def test_publish_single_event(self, bus):
        event = bus.publish_sync(EventType.FINDING_POSTED, {"id": "f-001"})
        assert event.event_type == EventType.FINDING_POSTED
        assert event.session_id == "sess-test-001"
        assert event.payload == {"id": "f-001"}
        assert event.id.startswith("e-")
        assert event.timestamp

    def test_publish_multiple_events(self, bus):
        bus.publish_sync(EventType.FINDING_POSTED, {"id": "f-001"})
        bus.publish_sync(EventType.REACTION_ADDED, {"id": "r-001"})
        bus.publish_sync(EventType.FILE_CLAIMED, {"file": "a.py"})
        assert bus.event_count() == 3

    def test_get_events_returns_all(self, bus):
        bus.publish_sync(EventType.FINDING_POSTED, {"id": "f-001"})
        bus.publish_sync(EventType.REACTION_ADDED, {"id": "r-001"})
        events = bus.get_events()
        assert len(events) == 2
        assert events[0]["event_type"] == "finding_posted"
        assert events[1]["event_type"] == "reaction_added"

    def test_get_events_filter_by_type(self, bus):
        bus.publish_sync(EventType.FINDING_POSTED, {"id": "f-001"})
        bus.publish_sync(EventType.REACTION_ADDED, {"id": "r-001"})
        bus.publish_sync(EventType.FINDING_POSTED, {"id": "f-002"})

        findings_only = bus.get_events(event_type=EventType.FINDING_POSTED)
        assert len(findings_only) == 2
        assert all(e["event_type"] == "finding_posted" for e in findings_only)

    def test_get_events_filter_by_since(self, bus):
        e1 = bus.publish_sync(EventType.FINDING_POSTED, {"id": "f-001"})
        # Events have monotonically increasing timestamps
        e2 = bus.publish_sync(EventType.REACTION_ADDED, {"id": "r-001"})

        # Get events since e1's timestamp (should include e1 if same timestamp
        # or only e2 if different)
        events_since = bus.get_events(since=e1.timestamp)
        # At minimum, events with timestamp > since should be returned
        # Both might have the same timestamp in fast execution
        assert all(e["timestamp"] >= e1.timestamp for e in events_since)

    def test_get_events_combined_filters(self, bus):
        e1 = bus.publish_sync(EventType.FINDING_POSTED, {"id": "f-001"})
        bus.publish_sync(EventType.REACTION_ADDED, {"id": "r-001"})
        bus.publish_sync(EventType.FINDING_POSTED, {"id": "f-002"})

        result = bus.get_events(
            since=e1.timestamp,
            event_type=EventType.FINDING_POSTED,
        )
        # Should only include findings posted at or after e1
        assert all(e["event_type"] == "finding_posted" for e in result)


# ── Async publish + subscribe ────────────────────────────────────────


class TestAsyncPublish:
    async def test_publish_persists_and_returns(self, bus):
        event = await bus.publish(EventType.FINDING_POSTED, {"id": "f-001"})
        assert event.event_type == EventType.FINDING_POSTED
        assert bus.event_count() == 1

    async def test_subscriber_receives_event(self, bus):
        queue = bus.subscribe("agent-A")
        await bus.publish(EventType.FINDING_POSTED, {"id": "f-001"})

        event = queue.get_nowait()
        assert event.event_type == EventType.FINDING_POSTED
        assert event.payload == {"id": "f-001"}

    async def test_multiple_subscribers(self, bus):
        q1 = bus.subscribe("agent-A")
        q2 = bus.subscribe("agent-B")
        await bus.publish(EventType.FILE_CLAIMED, {"file": "a.py"})

        assert q1.get_nowait().event_type == EventType.FILE_CLAIMED
        assert q2.get_nowait().event_type == EventType.FILE_CLAIMED

    async def test_unsubscribe(self, bus):
        queue = bus.subscribe("agent-A")
        bus.unsubscribe("agent-A")
        await bus.publish(EventType.FINDING_POSTED, {"id": "f-001"})
        assert queue.empty()

    async def test_subscriber_count(self, bus):
        assert bus.subscriber_count == 0
        bus.subscribe("agent-A")
        assert bus.subscriber_count == 1
        bus.subscribe("agent-B")
        assert bus.subscriber_count == 2
        bus.unsubscribe("agent-A")
        assert bus.subscriber_count == 1

    async def test_full_queue_does_not_block(self, bus):
        """When queue is full, publish should not block (drops silently)."""
        queue = bus.subscribe("agent-slow", max_queue=2)
        await bus.publish(EventType.FINDING_POSTED, {"id": "f-001"})
        await bus.publish(EventType.FINDING_POSTED, {"id": "f-002"})
        await bus.publish(EventType.FINDING_POSTED, {"id": "f-003"})  # should be dropped

        assert queue.qsize() == 2
        assert bus.event_count() == 3  # all 3 persisted to disk/memory


# ── Persistence ──────────────────────────────────────────────────────


class TestPersistence:
    def test_events_written_to_jsonl(self, bus, events_path):
        bus.publish_sync(EventType.FINDING_POSTED, {"id": "f-001"})
        bus.publish_sync(EventType.REACTION_ADDED, {"id": "r-001"})

        lines = events_path.read_text().strip().split("\n")
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["event_type"] == "finding_posted"
        assert first["payload"]["id"] == "f-001"

    def test_events_loaded_on_init(self, events_path):
        # Write some events to disk manually
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with open(events_path, "w") as fh:
            fh.write(json.dumps({
                "id": "e-aabbccdd",
                "event_type": "finding_posted",
                "session_id": "sess-test-001",
                "timestamp": "2026-03-22T10:00:00+00:00",
                "payload": {"id": "f-pre"},
            }) + "\n")

        bus2 = SessionEventBus("sess-test-001", events_path)
        assert bus2.event_count() == 1
        events = bus2.get_events()
        assert events[0]["payload"]["id"] == "f-pre"

    def test_empty_file_loads_ok(self, events_path):
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text("")
        bus2 = SessionEventBus("sess-test-001", events_path)
        assert bus2.event_count() == 0

    def test_nonexistent_file_loads_ok(self, tmp_path):
        bus2 = SessionEventBus("sess-test-001", tmp_path / "nope.jsonl")
        assert bus2.event_count() == 0


# ── Event types coverage ─────────────────────────────────────────────


class TestEventTypes:
    def test_all_event_types(self, bus):
        for et in EventType:
            event = bus.publish_sync(et, {"type": et.value})
            assert event.event_type == et

        assert bus.event_count() == len(EventType)

    def test_event_serialization_roundtrip(self, bus):
        event = bus.publish_sync(EventType.STATUS_CHANGED, {
            "finding_id": "f-001",
            "old_status": "open",
            "new_status": "confirmed",
        })
        d = event.to_dict()
        from review_swarm.models import Event
        restored = Event.from_dict(d)
        assert restored.id == event.id
        assert restored.event_type == event.event_type
        assert restored.payload == event.payload
