"""Integration test: full MCP tool flow via direct Python calls.

Tests the server's tool handler logic without starting an actual MCP server.
We call the handler functions directly to verify the end-to-end flow.
"""
import json
from pathlib import Path

import pytest

from review_swarm.server import create_app_context, tool_start_session, tool_end_session
from review_swarm.server import tool_get_session, tool_list_sessions, tool_suggest_experts
from review_swarm.server import tool_claim_file, tool_release_file, tool_get_claims
from review_swarm.server import tool_post_finding, tool_get_findings, tool_react, tool_get_summary
from review_swarm.server import tool_get_events
from review_swarm.server import tool_send_message, tool_get_inbox, tool_get_thread, tool_broadcast
from review_swarm.config import Config
from review_swarm.models import EventType


@pytest.fixture
def app_ctx(tmp_path, sample_project):
    config = Config(storage_dir=str(tmp_path))
    config.sessions_path.mkdir(parents=True, exist_ok=True)
    return create_app_context(config, project_path_override=str(sample_project))


class TestFullFlow:
    def test_session_lifecycle(self, app_ctx, sample_project):
        # Start session
        result = tool_start_session(app_ctx, str(sample_project), "Test")
        session_id = result["session_id"]
        assert session_id.startswith("sess-")

        # Get session
        session = tool_get_session(app_ctx, session_id)
        assert session["status"] == "active"

        # List sessions
        sessions = tool_list_sessions(app_ctx)
        assert len(sessions) == 1

        # End session
        end_result = tool_end_session(app_ctx, session_id)
        assert end_result["status"] == "completed"

    def test_finding_flow(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        # Post finding
        finding = tool_post_finding(app_ctx, sid,
            expert_role="threading-safety",
            file="src/main.py", line_start=1, line_end=5,
            severity="high", category="bug",
            title="Race condition",
            actual="No lock", expected="Should have lock",
            source_ref="src/main.py:1",
            suggestion_action="fix", suggestion_detail="Add lock",
            confidence=0.9,
        )
        fid = finding["id"]

        # Get findings
        findings = tool_get_findings(app_ctx, sid)
        assert len(findings) == 1

        # React: confirm
        tool_react(app_ctx, sid, "api-signatures", fid, "confirm", "Verified")
        tool_react(app_ctx, sid, "consistency", fid, "confirm", "Also verified")

        # Check status is confirmed
        findings = tool_get_findings(app_ctx, sid, status="confirmed")
        assert len(findings) == 1

    def test_claim_flow(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        # Claim
        claim = tool_claim_file(app_ctx, sid, "src/main.py", "threading-safety")
        assert claim["file"] == "src/main.py"

        # Get claims
        claims = tool_get_claims(app_ctx, sid)
        assert len(claims) == 1

        # Release
        tool_release_file(app_ctx, sid, "src/main.py", "threading-safety")
        claims = tool_get_claims(app_ctx, sid)
        assert len(claims) == 0

    def test_summary(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        tool_post_finding(app_ctx, sid,
            expert_role="threading-safety",
            file="src/main.py", line_start=1, line_end=5,
            severity="critical", category="bug",
            title="Deadlock risk",
            actual="Lock A then B", expected="Lock B then A",
            source_ref="src/main.py:1",
            suggestion_action="fix", suggestion_detail="Reorder locks",
            confidence=0.95,
        )

        report = tool_get_summary(app_ctx, sid, fmt="markdown")
        assert "Deadlock risk" in report

        report_json = tool_get_summary(app_ctx, sid, fmt="json")
        data = json.loads(report_json)
        assert data["summary"]["total"] == 1

    def test_suggest_experts(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        suggestions = tool_suggest_experts(app_ctx, sid)
        assert len(suggestions) > 0
        names = [s["profile_name"] for s in suggestions]
        assert "threading-safety" in names


class TestEventBusIntegration:
    """Test event bus integration via sync publish_sync from tool handlers."""

    def test_event_bus_created_for_session(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]
        bus = app_ctx.session_manager.get_event_bus(sid)
        assert bus is not None
        assert bus.event_count() == 0

    def test_publish_sync_and_get_events(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        finding = tool_post_finding(app_ctx, sid,
            expert_role="threading-safety",
            file="src/main.py", line_start=1, line_end=5,
            severity="high", category="bug",
            title="Race condition",
            actual="No lock", expected="Should have lock",
            source_ref="src/main.py:1",
            suggestion_action="fix", suggestion_detail="Add lock",
            confidence=0.9,
        )

        # Event publishing is now only done in MCP async wrappers.
        # For direct Python callers, publish manually via bus.publish_sync().
        bus = app_ctx.session_manager.get_event_bus(sid)
        bus.publish_sync(EventType.FINDING_POSTED, finding)

        events = tool_get_events(app_ctx, sid)
        assert len(events) >= 1
        assert events[0]["event_type"] == "finding_posted"
        assert events[0]["payload"]["id"] == finding["id"]

    def test_react_events(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]
        bus = app_ctx.session_manager.get_event_bus(sid)

        finding = tool_post_finding(app_ctx, sid,
            expert_role="threading-safety",
            file="src/main.py", line_start=1, line_end=5,
            severity="high", category="bug",
            title="Race condition",
            actual="No lock", expected="Should have lock",
            source_ref="src/main.py:1",
            suggestion_action="fix", suggestion_detail="Add lock",
            confidence=0.9,
        )
        fid = finding["id"]
        bus.publish_sync(EventType.FINDING_POSTED, finding)

        # First confirm
        r1 = tool_react(app_ctx, sid, "api-signatures", fid, "confirm", "Verified")
        bus.publish_sync(EventType.REACTION_ADDED, r1)

        # Second confirm -> status changes to confirmed
        old_status = r1["status"]
        r2 = tool_react(app_ctx, sid, "consistency", fid, "confirm", "Also verified")
        bus.publish_sync(EventType.REACTION_ADDED, r2)
        if r2["status"] != old_status:
            bus.publish_sync(EventType.STATUS_CHANGED, {
                "finding_id": fid,
                "old_status": old_status,
                "new_status": r2["status"],
            })

        events = tool_get_events(app_ctx, sid)
        types = [e["event_type"] for e in events]
        assert "finding_posted" in types
        assert "reaction_added" in types
        assert "status_changed" in types

    def test_claim_events(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]
        bus = app_ctx.session_manager.get_event_bus(sid)

        claim = tool_claim_file(app_ctx, sid, "src/main.py", "threading-safety")
        bus.publish_sync(EventType.FILE_CLAIMED, claim)

        tool_release_file(app_ctx, sid, "src/main.py", "threading-safety")
        bus.publish_sync(EventType.FILE_RELEASED, {
            "file": "src/main.py",
            "expert_role": "threading-safety",
            "status": "released",
        })

        events = tool_get_events(app_ctx, sid)
        types = [e["event_type"] for e in events]
        assert "file_claimed" in types
        assert "file_released" in types

    def test_get_events_filter_by_type(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]
        bus = app_ctx.session_manager.get_event_bus(sid)

        bus.publish_sync(EventType.FINDING_POSTED, {"id": "f-001"})
        bus.publish_sync(EventType.FILE_CLAIMED, {"file": "a.py"})
        bus.publish_sync(EventType.FINDING_POSTED, {"id": "f-002"})

        findings_only = tool_get_events(app_ctx, sid, event_type="finding_posted")
        assert len(findings_only) == 2
        assert all(e["event_type"] == "finding_posted" for e in findings_only)

    def test_events_persist_to_disk(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]
        bus = app_ctx.session_manager.get_event_bus(sid)

        bus.publish_sync(EventType.FINDING_POSTED, {"id": "f-001"})
        bus.publish_sync(EventType.REACTION_ADDED, {"id": "r-001"})

        # Verify events.jsonl exists and has content
        sess_dir = app_ctx.config.sessions_path / sid
        events_file = sess_dir / "events.jsonl"
        assert events_file.exists()
        lines = events_file.read_text().strip().split("\n")
        assert len(lines) == 2


class TestFilePathValidation:
    """Test that post_finding rejects invalid file paths."""

    def test_rejects_path_traversal(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        with pytest.raises(ValueError, match="Invalid file path"):
            tool_post_finding(app_ctx, sid,
                expert_role="security",
                file="../../../etc/passwd",
                line_start=1, line_end=1,
                severity="critical", category="security",
                title="Path traversal test",
                actual="n/a", expected="n/a",
                source_ref="n/a",
                suggestion_action="fix", suggestion_detail="n/a",
                confidence=0.9,
            )

    def test_rejects_absolute_path_unix(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        with pytest.raises(ValueError, match="Invalid file path"):
            tool_post_finding(app_ctx, sid,
                expert_role="security",
                file="/etc/passwd",
                line_start=1, line_end=1,
                severity="critical", category="security",
                title="Absolute path test",
                actual="n/a", expected="n/a",
                source_ref="n/a",
                suggestion_action="fix", suggestion_detail="n/a",
                confidence=0.9,
            )

    def test_rejects_backslash_path(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        with pytest.raises(ValueError, match="Invalid file path"):
            tool_post_finding(app_ctx, sid,
                expert_role="security",
                file="src\\main.py",
                line_start=1, line_end=1,
                severity="critical", category="security",
                title="Backslash path test",
                actual="n/a", expected="n/a",
                source_ref="n/a",
                suggestion_action="fix", suggestion_detail="n/a",
                confidence=0.9,
            )

    def test_accepts_valid_relative_path(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        # Should NOT raise
        finding = tool_post_finding(app_ctx, sid,
            expert_role="security",
            file="src/main.py",
            line_start=1, line_end=5,
            severity="medium", category="bug",
            title="Valid path test",
            actual="n/a", expected="n/a",
            source_ref="src/main.py:1",
            suggestion_action="fix", suggestion_detail="n/a",
            confidence=0.9,
        )
        assert finding["file"] == "src/main.py"


class TestMessagingIntegration:
    """Test agent-to-agent messaging through tool handler functions."""

    def test_direct_message_flow(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        # Agent A sends direct message to Agent B
        msg = tool_send_message(app_ctx, sid,
            from_agent="threading-safety",
            to_agent="api-signatures",
            content="Check lines 42-58 in server.py for lock issues",
            message_type="direct",
        )
        assert msg["message_type"] == "direct"
        assert msg["from_agent"] == "threading-safety"

        # Agent B checks inbox
        inbox = tool_get_inbox(app_ctx, sid, "api-signatures")
        assert len(inbox) == 1
        assert inbox[0]["content"] == "Check lines 42-58 in server.py for lock issues"

        # Agent A's inbox is empty (sent, not received)
        assert len(tool_get_inbox(app_ctx, sid, "threading-safety")) == 0

    def test_broadcast_flow(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        # Register agents first by sending any message
        tool_send_message(app_ctx, sid, "api-signatures", "*", "init", message_type="broadcast")
        tool_send_message(app_ctx, sid, "consistency", "*", "init", message_type="broadcast")

        # Agent A broadcasts
        msg = tool_broadcast(app_ctx, sid,
            from_agent="threading-safety",
            content="I found 3 critical issues in server.py",
        )
        assert msg["to_agent"] == "*"

        # Both B and C receive it
        inbox_b = tool_get_inbox(app_ctx, sid, "api-signatures")
        inbox_c = tool_get_inbox(app_ctx, sid, "consistency")
        # Filter for the specific broadcast (not init messages)
        b_msgs = [m for m in inbox_b if m["from_agent"] == "threading-safety"]
        c_msgs = [m for m in inbox_c if m["from_agent"] == "threading-safety"]
        assert len(b_msgs) == 1
        assert len(c_msgs) == 1

    def test_query_response_flow(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        # Register all agents
        tool_send_message(app_ctx, sid, "api-signatures", "*", "init", message_type="broadcast")
        tool_send_message(app_ctx, sid, "consistency", "*", "init", message_type="broadcast")

        # Agent A asks a question
        query = tool_send_message(app_ctx, sid,
            from_agent="threading-safety",
            to_agent="*",
            content="Has anyone seen lock contention in cache.py?",
            message_type="query",
        )
        query_id = query["id"]

        # Agent B responds
        tool_send_message(app_ctx, sid,
            from_agent="api-signatures",
            to_agent="threading-safety",
            content="Yes, lines 20-35 use a global lock",
            message_type="response",
            in_reply_to=query_id,
        )

        # Agent C responds
        tool_send_message(app_ctx, sid,
            from_agent="consistency",
            to_agent="threading-safety",
            content="The lock pattern is inconsistent with utils.py",
            message_type="response",
            in_reply_to=query_id,
        )

        # Agent A sees both responses in inbox
        inbox = tool_get_inbox(app_ctx, sid, "threading-safety")
        responses = [m for m in inbox if m["message_type"] == "response"]
        assert len(responses) == 2

        # Thread view shows query + 2 responses
        thread = tool_get_thread(app_ctx, sid, query_id)
        assert len(thread) == 3

    def test_star_topology_all_agents_connected(self, app_ctx, sample_project):
        """Every agent can reach every other agent."""
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]
        agents = ["threading-safety", "api-signatures", "consistency"]

        # Register all agents
        for agent in agents:
            tool_send_message(app_ctx, sid, agent, "*", "register", message_type="broadcast")

        # Each sends direct to each other
        for sender in agents:
            for receiver in agents:
                if sender != receiver:
                    tool_send_message(app_ctx, sid, sender, receiver,
                        f"Hello from {sender}", message_type="direct")

        # Verify full mesh connectivity
        for agent in agents:
            inbox = tool_get_inbox(app_ctx, sid, agent)
            direct_msgs = [m for m in inbox if m["message_type"] == "direct"]
            senders = {m["from_agent"] for m in direct_msgs}
            expected = set(agents) - {agent}
            assert senders == expected, f"{agent} missing messages from {expected - senders}"

    def test_messages_persist_to_disk(self, app_ctx, sample_project):
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        tool_send_message(app_ctx, sid, "threading-safety", "api-signatures",
            "Persisted message", message_type="direct")

        sess_dir = app_ctx.config.sessions_path / sid
        messages_file = sess_dir / "messages.jsonl"
        assert messages_file.exists()
        lines = messages_file.read_text().strip().split("\n")
        assert len(lines) == 1

    def test_pending_injected_into_post_finding(self, app_ctx, sample_project):
        """_pending appears in post_finding response when agent has unread messages."""
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        # Register agents and send a query to threading-safety
        mbus = app_ctx.session_manager.get_message_bus(sid)
        mbus.register_agent("threading-safety")
        mbus.register_agent("api-signatures")
        mbus.send_query(sid, "api-signatures", "Is there a lock pattern in server.py?")

        # threading-safety posts a finding -- response should include _pending
        finding = tool_post_finding(app_ctx, sid,
            expert_role="threading-safety",
            file="src/main.py", line_start=1, line_end=5,
            severity="high", category="bug",
            title="Race condition",
            actual="No lock", expected="Should have lock",
            source_ref="src/main.py:1",
            suggestion_action="fix", suggestion_detail="Add lock",
            confidence=0.9,
        )
        # Manually inject pending (simulating what MCP wrapper does)
        from review_swarm.server import _inject_pending
        _inject_pending(app_ctx, sid, "threading-safety", finding)

        assert "_pending" in finding
        assert finding["_pending"]["count"] == 1
        assert finding["_pending"]["urgent"] == 1  # queries are always urgent
        assert finding["_pending"]["preview"][0]["from_agent"] == "api-signatures"

    def test_message_with_context(self, app_ctx, sample_project):
        """Messages can carry structured context about findings."""
        result = tool_start_session(app_ctx, str(sample_project))
        sid = result["session_id"]

        finding = tool_post_finding(app_ctx, sid,
            expert_role="threading-safety",
            file="src/main.py", line_start=42, line_end=58,
            severity="critical", category="bug",
            title="Race condition in cache",
            actual="No lock on write", expected="Lock required",
            source_ref="src/main.py:45",
            suggestion_action="fix", suggestion_detail="Add lock",
            confidence=0.92,
        )

        # Send message with finding context
        msg = tool_send_message(app_ctx, sid,
            from_agent="threading-safety",
            to_agent="api-signatures",
            content="Can you verify this race condition?",
            message_type="direct",
            urgent=True,
            context={
                "finding_id": finding["id"],
                "file": "src/main.py",
                "line_start": 42,
                "line_end": 58,
                "title": "Race condition in cache",
                "severity": "critical",
            },
        )
        assert msg["context"]["finding_id"] == finding["id"]

        # Recipient sees the context
        inbox = tool_get_inbox(app_ctx, sid, "api-signatures")
        assert len(inbox) == 1
        assert inbox[0]["context"]["finding_id"] == finding["id"]
        assert inbox[0]["context"]["severity"] == "critical"
        assert inbox[0]["urgent"] is True
