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
from review_swarm.config import Config


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
