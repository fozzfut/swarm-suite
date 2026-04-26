"""End-to-end MCP test: real client + real server over in-memory streams.

Where test_mcp_server_smoke.py only verifies tool *registration*, this
file goes the rest of the way: spins up the live FastMCP server with
its full lifespan (so the per-request stores are actually injected),
connects an `mcp.client.session.ClientSession` over `anyio` memory
pipes, and makes real `call_tool` requests. This is the closest
in-process substitute for "Claude Code talks to swarm-kb over stdio".

Catches the failure modes test_mcp_server_smoke.py cannot:
  * lifespan-context wiring (the dataclass field path the per-tool
    handlers reach through)
  * argument schema mismatches between MCP and handler
  * JSON serialisation of the tool's return value
  * the cross-tool flow inside a single MCP "session"

Each test isolates the KB root via tmp_path + monkeypatched HOME so the
in-memory server's bootstrap() lands on a clean filesystem and does not
pollute the user's `~/.swarm-kb/`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from swarm_kb.server import create_mcp_server


@pytest.fixture
def kb_root(tmp_path, monkeypatch):
    """Force every store + bootstrap() onto a clean tmp KB root."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cfg_dir = tmp_path / ".swarm-kb"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        f"storage_root: {cfg_dir.as_posix()}\n", encoding="utf-8"
    )
    return cfg_dir


def _text(result) -> str:
    """Pull the text payload out of a CallToolResult."""
    # mcp 1.x returns content list of TextContent / ImageContent / ...
    parts = result.content
    return parts[0].text if parts and hasattr(parts[0], "text") else ""


def _json_text(result) -> dict | list:
    """Parse the JSON-encoded text payload (every kb_* tool returns JSON)."""
    return json.loads(_text(result))


# ---------------------------------------------------------------------------
# Smoke: server starts, list_tools works, total count is sane
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_starts_and_lists_tools(kb_root):
    server = create_mcp_server()
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()
        tools = await client.list_tools()
        names = {t.name for t in tools.tools}
        # Sanity: pre-existing + 30+ swarms-import tools = >=80
        assert len(names) >= 80
        # A handful of canonical ones must be present.
        for n in ("kb_status", "kb_navigator_state",
                  "kb_subtask_done", "kb_complete_task",
                  "kb_start_judging", "kb_start_pgve",
                  "kb_start_flow", "kb_route_experts"):
            assert n in names, f"missing {n}"


# ---------------------------------------------------------------------------
# Lifespan-context wiring -- the failure mode smoke tests can't reach
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judging_full_lifecycle_via_real_mcp(kb_root):
    server = create_mcp_server()
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()

        # Start a judging.
        r = await client.call_tool(
            "kb_start_judging",
            {"subject": "review fp-7c2a", "dimensions": "correctness,regression"},
        )
        j = _json_text(r)
        jid = j["id"]
        assert j["status"] == "open"
        assert set(j["dimensions"]) == {"correctness", "regression"}

        # Submit one judgment per dimension.
        await client.call_tool("kb_judge_dimension", {
            "judging_id": jid, "judge": "threading", "dimension": "correctness",
            "verdict": "pass", "rationale": "lock release on exception path is correct",
        })
        r = await client.call_tool("kb_judge_dimension", {
            "judging_id": jid, "judge": "perf", "dimension": "regression",
            "verdict": "mixed", "rationale": "2ms overhead under contention",
        })
        assert _json_text(r)["is_complete"] is True

        # Synthesise.
        r = await client.call_tool("kb_resolve_judging", {
            "judging_id": jid, "overall": "pass",
            "summary": "net positive tradeoff",
        })
        assert _json_text(r)["overall"] == "pass"

        # Read back -- status must be resolved.
        r = await client.call_tool("kb_get_judging", {"judging_id": jid})
        loaded = _json_text(r)
        assert loaded["status"] == "resolved"
        assert loaded["synthesis"]["summary"] == "net positive tradeoff"


@pytest.mark.asyncio
async def test_pgve_full_lifecycle_via_real_mcp(kb_root):
    server = create_mcp_server()
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()

        r = await client.call_tool(
            "kb_start_pgve",
            {"task_spec": "implement file lock", "max_candidates": 3},
        )
        sid = _json_text(r)["id"]

        c1 = _json_text(await client.call_tool("kb_submit_candidate", {
            "session_id": sid, "generator": "fix-1", "content": "patch v1",
        }))
        assert c1["previous_feedback"] == ""

        e1 = _json_text(await client.call_tool("kb_evaluate_candidate", {
            "session_id": sid, "evaluator": "reviewer",
            "verdict": "revise", "feedback": "lock leak on exception",
        }))
        assert e1["session_status"] == "open"

        c2 = _json_text(await client.call_tool("kb_submit_candidate", {
            "session_id": sid, "generator": "fix-1", "content": "patch v2",
        }))
        assert "lock leak" in c2["previous_feedback"]

        e2 = _json_text(await client.call_tool("kb_evaluate_candidate", {
            "session_id": sid, "evaluator": "reviewer",
            "verdict": "accepted", "feedback": "lgtm",
        }))
        assert e2["session_status"] == "accepted"


@pytest.mark.asyncio
async def test_dsl_flow_lifecycle_via_real_mcp(kb_root):
    server = create_mcp_server()
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()

        # Start a flow with a gate.
        r = _json_text(await client.call_tool("kb_start_flow", {
            "source": "a -> H -> b",
            "known_names": "a\nb",
        }))
        fid = r["flow"]["id"]
        first = r["next_steps"][0]
        assert first["kind"] == "atom" and first["name"] == "a"

        # Mark a done.
        r = _json_text(await client.call_tool("kb_mark_step_done", {
            "flow_id": fid, "step_id": first["id"],
        }))
        assert r["status"] == "open"
        gate = r["next_steps"][0]
        assert gate["kind"] == "gate"

        # Mark gate done.
        r = _json_text(await client.call_tool("kb_mark_step_done", {
            "flow_id": fid, "step_id": gate["id"],
        }))
        b_step = r["next_steps"][0]
        assert b_step["name"] == "b"

        # Mark b done -- flow completes.
        r = _json_text(await client.call_tool("kb_mark_step_done", {
            "flow_id": fid, "step_id": b_step["id"],
        }))
        assert r["status"] == "completed"
        assert r["next_steps"] == []


@pytest.mark.asyncio
async def test_navigator_state_via_real_mcp(kb_root, tmp_path):
    server = create_mcp_server()
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()

        proj = str(tmp_path / "proj")
        Path(proj).mkdir()

        # No pipeline yet -> snapshot returns "start" suggestion.
        r = _json_text(await client.call_tool(
            "kb_navigator_state", {"project_path": proj},
        ))
        assert r["active_pipeline"] is None
        suggestions = r["suggested_next_steps"]
        assert any(s["kind"] == "start" for s in suggestions)


@pytest.mark.asyncio
async def test_completion_full_lifecycle_via_real_mcp(kb_root):
    server = create_mcp_server()
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()

        # Pre-create a session dir under the tmp KB root.
        sess_dir = kb_root / "review" / "sessions" / "sess-e2e"
        sess_dir.mkdir(parents=True, exist_ok=True)
        (sess_dir / "meta.json").write_text("{}", encoding="utf-8")

        sub = _json_text(await client.call_tool("kb_subtask_done", {
            "tool": "review", "session_id": "sess-e2e",
            "subtask_id": "scan", "summary": "scanned 12 files",
        }))
        assert sub["subtask"]["id"] == "scan"

        think = _json_text(await client.call_tool("kb_record_think", {
            "tool": "review", "session_id": "sess-e2e",
        }))
        assert think["consecutive_thinks"] == 1

        action = _json_text(await client.call_tool("kb_record_action", {
            "tool": "review", "session_id": "sess-e2e",
        }))
        assert action["consecutive_thinks"] == 0

        done = _json_text(await client.call_tool("kb_complete_task", {
            "tool": "review", "session_id": "sess-e2e",
            "summary": "all done",
        }))
        assert done["completion"]["summary"] == "all done"

        state = _json_text(await client.call_tool("kb_get_completion", {
            "tool": "review", "session_id": "sess-e2e",
        }))
        assert state["should_stop"] is True
        assert state["stop_reason"] == "completed"


# ---------------------------------------------------------------------------
# Cross-flow: judging referenced from a verification, both via real MCP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verification_with_judging_evidence_via_real_mcp(kb_root):
    server = create_mcp_server()
    async with create_connected_server_and_client_session(server) as client:
        await client.initialize()

        # 1. Run a judging on a fix candidate.
        j = _json_text(await client.call_tool("kb_start_judging", {
            "subject": "verify fp-x",
            "dimensions": "test_coverage,no_regression",
        }))
        jid = j["id"]
        for dim in ("test_coverage", "no_regression"):
            await client.call_tool("kb_judge_dimension", {
                "judging_id": jid, "judge": "qa",
                "dimension": dim, "verdict": "pass",
                "rationale": f"{dim} ok",
            })
        await client.call_tool("kb_resolve_judging", {
            "judging_id": jid, "overall": "pass", "summary": "ready",
        })

        # 2. Build a verification report referencing the judging.
        v = _json_text(await client.call_tool("kb_start_verification", {
            "fix_session": "fix-e2e",
        }))
        rid = v["id"]
        await client.call_tool("kb_add_verification_evidence", {
            "report_id": rid, "kind": "test_diff",
            "summary": "155 -> 158 passing",
            "data": '{"before": 155, "after": 158}',
        })
        await client.call_tool("kb_add_verification_evidence", {
            "report_id": rid, "kind": "judging",
            "summary": "qa council passed",
            "data": json.dumps({"judging_id": jid, "overall": "pass"}),
        })
        verdict = _json_text(await client.call_tool("kb_finalise_verification", {
            "report_id": rid, "overall": "pass",
            "summary": "evidence positive",
        }))
        assert verdict["overall"] == "pass"

        # 3. Reload + assert the cross-link survived.
        loaded = _json_text(await client.call_tool("kb_get_verification", {
            "report_id": rid,
        }))
        assert loaded["status"] == "finalised"
        judging_evs = [e for e in loaded["evidence"] if e["kind"] == "judging"]
        assert len(judging_evs) == 1
        assert judging_evs[0]["data"]["judging_id"] == jid
