"""Tests for MessageBus -- star topology agent-to-agent communication."""

import json

import pytest

from review_swarm.message_bus import MessageBus
from review_swarm.models import Message, MessageType


@pytest.fixture
def bus(tmp_path):
    b = MessageBus("sess-test-001", tmp_path / "messages.jsonl")
    b.register_agent("threading-safety")
    b.register_agent("api-signatures")
    b.register_agent("consistency")
    return b


@pytest.fixture
def messages_path(tmp_path):
    return tmp_path / "messages.jsonl"


# ── Direct messages ──────────────────────────────────────────────────


class TestDirectMessages:
    def test_send_direct(self, bus):
        msg = bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "Check line 42")
        assert msg.message_type == MessageType.DIRECT
        assert msg.from_agent == "threading-safety"
        assert msg.to_agent == "api-signatures"
        assert msg.id.startswith("m-")

    def test_direct_appears_in_recipient_inbox(self, bus):
        bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "Check line 42")
        inbox = bus.get_inbox("api-signatures")
        assert len(inbox) == 1
        assert inbox[0]["content"] == "Check line 42"
        assert inbox[0]["from_agent"] == "threading-safety"

    def test_direct_not_in_sender_inbox(self, bus):
        bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "Check line 42")
        inbox = bus.get_inbox("threading-safety")
        assert len(inbox) == 0

    def test_direct_not_in_other_agent_inbox(self, bus):
        bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "Check line 42")
        inbox = bus.get_inbox("consistency")
        assert len(inbox) == 0


# ── Broadcast ────────────────────────────────────────────────────────


class TestBroadcast:
    def test_broadcast_reaches_all_except_sender(self, bus):
        bus.send_broadcast("sess-test-001", "threading-safety", "Starting review of server.py")
        assert len(bus.get_inbox("api-signatures")) == 1
        assert len(bus.get_inbox("consistency")) == 1
        assert len(bus.get_inbox("threading-safety")) == 0

    def test_broadcast_content(self, bus):
        bus.send_broadcast("sess-test-001", "threading-safety", "Starting review")
        msg = bus.get_inbox("api-signatures")[0]
        assert msg["content"] == "Starting review"
        assert msg["message_type"] == "broadcast"
        assert msg["to_agent"] == "*"


# ── Query / Response ─────────────────────────────────────────────────


class TestQueryResponse:
    def test_query_reaches_all_except_sender(self, bus):
        bus.send_query("sess-test-001", "threading-safety", "Has anyone seen a lock pattern in utils.py?")
        assert len(bus.get_inbox("api-signatures")) == 1
        assert len(bus.get_inbox("consistency")) == 1
        assert len(bus.get_inbox("threading-safety")) == 0

    def test_response_reaches_query_sender(self, bus):
        query = bus.send_query("sess-test-001", "threading-safety", "Any lock patterns?")
        bus.send_response("sess-test-001", "api-signatures", query.id, "Yes, line 42")

        # Response goes to the original query sender
        inbox = bus.get_inbox("threading-safety")
        responses = [m for m in inbox if m["message_type"] == "response"]
        assert len(responses) == 1
        assert responses[0]["content"] == "Yes, line 42"
        assert responses[0]["in_reply_to"] == query.id

    def test_get_thread(self, bus):
        query = bus.send_query("sess-test-001", "threading-safety", "Lock patterns?")
        bus.send_response("sess-test-001", "api-signatures", query.id, "Yes, line 42")
        bus.send_response("sess-test-001", "consistency", query.id, "Also line 58")

        thread = bus.get_thread(query.id)
        assert len(thread) == 3  # query + 2 responses
        types = [m["message_type"] for m in thread]
        assert types.count("query") == 1
        assert types.count("response") == 2

    def test_multiple_queries_independent(self, bus):
        q1 = bus.send_query("sess-test-001", "threading-safety", "Query 1?")
        q2 = bus.send_query("sess-test-001", "api-signatures", "Query 2?")
        bus.send_response("sess-test-001", "consistency", q1.id, "Answer to Q1")
        bus.send_response("sess-test-001", "consistency", q2.id, "Answer to Q2")

        thread1 = bus.get_thread(q1.id)
        thread2 = bus.get_thread(q2.id)
        assert len(thread1) == 2
        assert len(thread2) == 2


# ── Filtering ────────────────────────────────────────────────────────


class TestFiltering:
    def test_inbox_filter_by_type(self, bus):
        bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "Direct msg")
        bus.send_broadcast("sess-test-001", "consistency", "Broadcast msg")

        all_msgs = bus.get_inbox("api-signatures")
        assert len(all_msgs) == 2

        direct_only = bus.get_inbox("api-signatures", message_type="direct")
        assert len(direct_only) == 1
        assert direct_only[0]["message_type"] == "direct"

        broadcast_only = bus.get_inbox("api-signatures", message_type="broadcast")
        assert len(broadcast_only) == 1
        assert broadcast_only[0]["message_type"] == "broadcast"

    def test_inbox_filter_by_since(self, bus):
        msg1 = bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "First")
        msg2 = bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "Second")
        # Filter since msg1's timestamp
        result = bus.get_inbox("api-signatures", since=msg1.created_at)
        # Should at least include msgs after that timestamp
        assert all(m["created_at"] >= msg1.created_at for m in result)

    def test_get_all_messages(self, bus):
        bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "msg1")
        bus.send_broadcast("sess-test-001", "consistency", "msg2")
        all_msgs = bus.get_all_messages()
        assert len(all_msgs) == 2

    def test_get_all_messages_filter_by_type(self, bus):
        bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "msg1")
        bus.send_broadcast("sess-test-001", "consistency", "msg2")
        broadcasts = bus.get_all_messages(message_type="broadcast")
        assert len(broadcasts) == 1
        assert broadcasts[0]["message_type"] == "broadcast"


# ── Agent registration ───────────────────────────────────────────────


class TestRegistration:
    def test_register_agent(self, bus):
        assert "threading-safety" in bus.registered_agents
        assert "api-signatures" in bus.registered_agents

    def test_unregister_agent(self, bus):
        bus.unregister_agent("consistency")
        assert "consistency" not in bus.registered_agents
        # Broadcast after unregister doesn't reach removed agent
        bus.send_broadcast("sess-test-001", "threading-safety", "Hello")
        assert len(bus.get_inbox("consistency")) == 0

    def test_new_agent_receives_future_broadcasts(self, bus):
        bus.register_agent("security-surface")
        bus.send_broadcast("sess-test-001", "threading-safety", "Hello new agent")
        inbox = bus.get_inbox("security-surface")
        assert len(inbox) == 1


# ── Persistence ──────────────────────────────────────────────────────


class TestPersistence:
    def test_messages_written_to_jsonl(self, bus, messages_path):
        bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "msg1")
        bus.send_broadcast("sess-test-001", "consistency", "msg2")

        lines = messages_path.read_text().strip().split("\n")
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["message_type"] == "direct"
        assert first["content"] == "msg1"

    def test_messages_loaded_on_init(self, messages_path):
        messages_path.parent.mkdir(parents=True, exist_ok=True)
        msg = {
            "id": "m-aabbccdd",
            "session_id": "sess-test-001",
            "from_agent": "threading-safety",
            "to_agent": "api-signatures",
            "message_type": "direct",
            "content": "Persisted msg",
            "in_reply_to": "",
            "created_at": "2026-03-22T10:00:00+00:00",
        }
        with open(messages_path, "w") as fh:
            fh.write(json.dumps(msg) + "\n")

        bus2 = MessageBus("sess-test-001", messages_path)
        assert bus2.message_count() == 1
        inbox = bus2.get_inbox("api-signatures")
        assert len(inbox) == 1
        assert inbox[0]["content"] == "Persisted msg"

    def test_empty_file_loads_ok(self, messages_path):
        messages_path.parent.mkdir(parents=True, exist_ok=True)
        messages_path.write_text("")
        bus2 = MessageBus("sess-test-001", messages_path)
        assert bus2.message_count() == 0


# ── Star topology: full mesh via hub ─────────────────────────────────


class TestStarTopology:
    """Verify that every agent can reach every other agent."""

    def test_each_agent_can_message_each_other(self, bus):
        agents = ["threading-safety", "api-signatures", "consistency"]
        for sender in agents:
            for receiver in agents:
                if sender != receiver:
                    bus.send_direct("sess-test-001", sender, receiver,
                                   f"From {sender} to {receiver}")

        # Each agent should have messages from the other 2
        for agent in agents:
            inbox = bus.get_inbox(agent)
            senders = {m["from_agent"] for m in inbox}
            expected_senders = set(agents) - {agent}
            assert senders == expected_senders, f"{agent}'s inbox missing senders"

    def test_broadcast_forms_full_mesh(self, bus):
        agents = ["threading-safety", "api-signatures", "consistency"]
        # Each agent broadcasts once
        for agent in agents:
            bus.send_broadcast("sess-test-001", agent, f"Status from {agent}")

        # Each agent should see broadcasts from the other 2
        for agent in agents:
            inbox = bus.get_inbox(agent)
            senders = {m["from_agent"] for m in inbox}
            expected = set(agents) - {agent}
            assert senders == expected

    def test_query_response_roundtrip(self, bus):
        # Agent A asks, B and C respond, A sees all responses
        query = bus.send_query("sess-test-001", "threading-safety", "Anyone see race conditions?")
        bus.send_response("sess-test-001", "api-signatures", query.id, "Yes in server.py")
        bus.send_response("sess-test-001", "consistency", query.id, "Also in utils.py")

        inbox = bus.get_inbox("threading-safety")
        assert len(inbox) == 2  # two responses
        responders = {m["from_agent"] for m in inbox}
        assert responders == {"api-signatures", "consistency"}


# ── Pending notifications (piggyback) ────────────────────────────────


class TestPendingNotifications:
    def test_no_pending_when_no_messages(self, bus):
        pending = bus.get_pending("api-signatures")
        assert pending == {}

    def test_pending_shows_unread_messages(self, bus):
        bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "Check this")
        pending = bus.get_pending("api-signatures")
        assert pending["count"] == 1
        assert pending["urgent"] == 0
        assert len(pending["preview"]) == 1
        assert pending["preview"][0]["from_agent"] == "threading-safety"

    def test_pending_after_read_is_empty(self, bus):
        bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "Check this")
        # Read inbox (advances watermark)
        bus.get_inbox("api-signatures")
        # Now pending should be empty
        pending = bus.get_pending("api-signatures")
        assert pending == {}

    def test_pending_shows_new_messages_after_read(self, bus):
        import time
        bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "First")
        bus.get_inbox("api-signatures")  # mark as read
        time.sleep(0.01)  # ensure timestamp advances past watermark
        bus.send_direct("sess-test-001", "consistency", "api-signatures", "Second")
        pending = bus.get_pending("api-signatures")
        assert pending["count"] == 1
        assert pending["preview"][0]["from_agent"] == "consistency"

    def test_urgent_messages_prioritized(self, bus):
        bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "Normal msg")
        bus.send_query("sess-test-001", "consistency", "Urgent query?")
        pending = bus.get_pending("api-signatures")
        assert pending["count"] == 2
        assert pending["urgent"] == 1
        # Urgent should be first in preview
        assert pending["preview"][0]["urgent"] is True

    def test_queries_always_urgent(self, bus):
        query = bus.send_query("sess-test-001", "threading-safety", "Lock patterns?")
        assert query.urgent is True
        pending = bus.get_pending("api-signatures")
        assert pending["urgent"] == 1

    def test_pending_preview_limited(self, bus):
        for i in range(10):
            bus.send_direct("sess-test-001", "threading-safety", "api-signatures", f"Msg {i}")
        pending = bus.get_pending("api-signatures", max_preview=3)
        assert pending["count"] == 10
        assert len(pending["preview"]) == 3

    def test_mark_read_clears_pending(self, bus):
        bus.send_direct("sess-test-001", "threading-safety", "api-signatures", "Check this")
        bus.mark_read("api-signatures")
        pending = bus.get_pending("api-signatures")
        assert pending == {}


# ── Context (finding/file references) ────────────────────────────────


class TestMessageContext:
    def test_message_with_context(self, bus):
        msg = Message(
            id=Message.generate_id(),
            session_id="sess-test-001",
            from_agent="threading-safety",
            to_agent="api-signatures",
            message_type=MessageType.DIRECT,
            content="Check this race condition",
            context={
                "finding_id": "f-abc123",
                "file": "src/server.py",
                "line_start": 42,
                "line_end": 58,
                "title": "Race condition in cache update",
            },
        )
        bus.send(msg)
        inbox = bus.get_inbox("api-signatures")
        assert len(inbox) == 1
        assert inbox[0]["context"]["finding_id"] == "f-abc123"
        assert inbox[0]["context"]["file"] == "src/server.py"

    def test_context_persists_in_serialization(self, bus):
        ctx = {"finding_id": "f-001", "file": "a.py", "line_start": 1}
        msg = Message(
            id=Message.generate_id(),
            session_id="sess-test-001",
            from_agent="threading-safety",
            to_agent="api-signatures",
            message_type=MessageType.DIRECT,
            content="Check this",
            context=ctx,
        )
        d = msg.to_dict()
        restored = Message.from_dict(d)
        assert restored.context == ctx

    def test_query_with_context(self, bus):
        msg = Message(
            id=Message.generate_id(),
            session_id="sess-test-001",
            from_agent="threading-safety",
            to_agent="*",
            message_type=MessageType.QUERY,
            content="Is this lock pattern correct?",
            urgent=True,
            context={
                "finding_id": "f-xyz",
                "file": "src/cache.py",
                "line_start": 20,
                "line_end": 35,
            },
        )
        bus.send(msg)
        # Both other agents should see the query with context
        for agent in ["api-signatures", "consistency"]:
            inbox = bus.get_inbox(agent)
            queries = [m for m in inbox if m["message_type"] == "query"]
            assert len(queries) == 1
            assert queries[0]["context"]["finding_id"] == "f-xyz"
