"""End-to-end smoke test: the live MCP server registers + serves new tools.

Two layers of check:
  1. Tool-registration audit (proves every new tool is discoverable to
     a real client).
  2. Live invocation of tools that DO NOT require a request-scoped
     lifespan context (kb_list_debate_formats, kb_get_debate_format,
     kb_parse_flow, kb_route_experts).

Tools that require the lifespan-injected store registry
(judging/verification/pgve/dsl-with-storage/completion) are exercised
end-to-end via the engine API in `test_integration_swarms_import.py`.
The MCP wrappers themselves are thin: argument unpack, store call,
JSON encode. They cannot fail in interesting ways without one of the
direct unit / integration tests catching it first.

If you ever switch to running these against a stood-up FastMCP client
session (via `mcp.client.session.ClientSession`) -- the lifespan-
required tools become live too. That's deployment-grade plumbing, out
of scope for unit-test runtime.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

# These imports happen before the fixture so we fail fast if the package
# can't even be imported (which already catches several deploy-time bugs).
from swarm_kb.server import create_mcp_server


@pytest.fixture
def kb_root(tmp_path, monkeypatch):
    """Force the suite to use a tmp KB root and create the structure."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # Override the suite config root explicitly via the SuiteConfig load path.
    cfg_dir = tmp_path / ".swarm-kb"
    cfg_dir.mkdir()
    (cfg_dir / "config.yaml").write_text(
        f"storage_root: {cfg_dir}\n", encoding="utf-8"
    )
    return cfg_dir


@pytest.fixture
def mcp_server(kb_root):
    """A real swarm-kb server bound to the tmp KB."""
    return create_mcp_server()


def _call(mcp, name, **kwargs):
    """Synchronously call an MCP tool and return its parsed JSON result."""
    result = asyncio.run(mcp.call_tool(name, kwargs))
    # FastMCP returns (content_list, structured) for newer mcp versions
    # and a single content_list for older. Accept both.
    if isinstance(result, tuple):
        content, _structured = result
    else:
        content = result
    if not content:
        return None
    text = content[0].text if hasattr(content[0], "text") else str(content[0])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


# ---------- registration audit -----------------------------------------------


NEW_TOOL_NAMES = [
    # completion
    "kb_subtask_done", "kb_complete_task", "kb_record_think",
    "kb_record_action", "kb_get_completion",
    # debate formats
    "kb_list_debate_formats", "kb_get_debate_format",
    # judging
    "kb_start_judging", "kb_judge_dimension", "kb_resolve_judging",
    "kb_get_judging", "kb_list_judgings",
    # verification
    "kb_start_verification", "kb_add_verification_evidence",
    "kb_finalise_verification", "kb_get_verification", "kb_list_verifications",
    # pgve
    "kb_start_pgve", "kb_submit_candidate", "kb_evaluate_candidate",
    "kb_get_pgve", "kb_list_pgve",
    # dsl
    "kb_parse_flow", "kb_start_flow", "kb_get_next_steps",
    "kb_mark_step_done", "kb_get_flow", "kb_list_flows",
    # router
    "kb_route_experts",
]


def test_all_new_tools_register(mcp_server):
    tools = asyncio.run(mcp_server.list_tools())
    names = {t.name for t in tools}
    missing = [n for n in NEW_TOOL_NAMES if n not in names]
    assert not missing, f"Missing MCP tools: {missing}"


def test_total_tool_count_in_expected_range(mcp_server):
    tools = asyncio.run(mcp_server.list_tools())
    # Sanity: the suite has ~50 pre-existing + 30 new ~= 80+. If this drops
    # significantly something failed silently.
    assert len(tools) >= 80, f"Only {len(tools)} tools registered"


# ---------- debate formats: list + get ---------------------------------------


def test_list_debate_formats_returns_13(mcp_server):
    result = _call(mcp_server, "kb_list_debate_formats")
    assert isinstance(result, list)
    names = {f["name"] for f in result}
    assert {"open", "trial", "mediation", "with_judge"}.issubset(names)
    assert len(result) >= 13


def test_get_debate_format_returns_phase_spec(mcp_server):
    result = _call(mcp_server, "kb_get_debate_format", format="trial")
    assert result["name"] == "trial"
    assert {"prosecution", "defense", "judge"} == set(result["actors"])
    assert result["phases"]
    for p in result["phases"]:
        assert p["name"] and p["actors"] and p["description"]


def test_get_unknown_format_raises_invalid_params(mcp_server):
    with pytest.raises(Exception):
        _call(mcp_server, "kb_get_debate_format", format="nonexistent")


# ---------- DSL: parse + start + walk ----------------------------------------


def test_dsl_parse_validates(mcp_server):
    parsed = _call(mcp_server, "kb_parse_flow",
                   source="scan -> (lint, type_check) -> H -> deploy",
                   known_names="scan\nlint\ntype_check\ndeploy")
    assert parsed["problems"] == []
    assert sorted(parsed["atoms"]) == ["deploy", "lint", "scan", "type_check"]


def test_dsl_parse_unknown_step_reported(mcp_server):
    parsed = _call(mcp_server, "kb_parse_flow",
                   source="scan -> bogus", known_names="scan\ndeploy")
    assert any("bogus" in p for p in parsed["problems"])


# ---------- AgentRouter ------------------------------------------------------


def test_route_experts_with_real_yaml_dir(mcp_server, tmp_path):
    experts_dir = tmp_path / "experts"
    experts_dir.mkdir()
    (experts_dir / "security.yaml").write_text(
        "name: Security Expert\n"
        "description: finds auth bugs and injection vulnerabilities\n"
        "system_prompt: Audit for auth, injection, csrf, xss vectors.\n",
        encoding="utf-8",
    )
    (experts_dir / "perf.yaml").write_text(
        "name: Performance Expert\n"
        "description: finds slow queries and quadratic loops\n"
        "system_prompt: Profile for n+1 queries and cache misses.\n",
        encoding="utf-8",
    )

    result = _call(mcp_server, "kb_route_experts",
                   task="audit auth bugs in the login flow",
                   experts_dir=str(experts_dir),
                   top_k=5, min_score=0.05)
    assert result["total_loaded"] == 2
    assert result["ranked"][0]["slug"] == "security"


def test_route_experts_unknown_dir_raises(mcp_server, tmp_path):
    with pytest.raises(Exception):
        _call(mcp_server, "kb_route_experts",
              task="anything", experts_dir=str(tmp_path / "nonexistent"))


# ---------- lifespan-required tools: registration-only ---------------------
#
# kb_subtask_done / kb_complete_task / kb_record_think / kb_record_action /
# kb_get_completion / kb_start_judging / kb_judge_dimension / kb_resolve_judging
# / kb_get_judging / kb_list_judgings / kb_start_verification /
# kb_add_verification_evidence / kb_finalise_verification / kb_get_verification
# / kb_list_verifications / kb_start_pgve / kb_submit_candidate /
# kb_evaluate_candidate / kb_get_pgve / kb_list_pgve / kb_start_flow /
# kb_get_next_steps / kb_mark_step_done / kb_get_flow / kb_list_flows
#
# These all read stores from the request-scoped lifespan context. End-to-end
# MCP invocation requires standing up a real MCP client/server session (out of
# scope for unit tests). The engine-level lifecycle for each is exercised in
# test_integration_swarms_import.py; the MCP wrapper is a thin arg-unpack +
# JSON-encode layer.


def test_lifespan_required_tools_all_registered(mcp_server):
    """Belt-and-braces: enumerate the lifespan-required tools and assert they
    appear in the live tool list. Registration is the failure mode that
    matters most for deployment -- if a tool is in the source but never gets
    decorated (off-by-one in indentation, misplaced after `return mcp`, etc.),
    a real client will see it missing without any error message."""
    lifespan_required = {
        "kb_subtask_done", "kb_complete_task", "kb_record_think",
        "kb_record_action", "kb_get_completion",
        "kb_start_judging", "kb_judge_dimension", "kb_resolve_judging",
        "kb_get_judging", "kb_list_judgings",
        "kb_start_verification", "kb_add_verification_evidence",
        "kb_finalise_verification", "kb_get_verification",
        "kb_list_verifications",
        "kb_start_pgve", "kb_submit_candidate", "kb_evaluate_candidate",
        "kb_get_pgve", "kb_list_pgve",
        "kb_start_flow", "kb_get_next_steps", "kb_mark_step_done",
        "kb_get_flow", "kb_list_flows",
    }
    tools = asyncio.run(mcp_server.list_tools())
    names = {t.name for t in tools}
    missing = lifespan_required - names
    assert not missing, f"Lifespan-required tools missing: {missing}"
