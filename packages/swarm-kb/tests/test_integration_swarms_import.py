"""Integration tests for the swarms-import feature set.

These tests exercise full cross-module lifecycles, not unit boundaries:
they verify that completion/judging/verification/pgve/dsl/debate
modules compose correctly under realistic usage. Each test:
  1. Walks a full happy-path scenario end-to-end.
  2. Reloads stores from disk to confirm persistence is round-trip safe.
  3. Asserts state at every step (no fire-and-forget).

If a unit-level concern needs a separate test, it goes in the per-module
test files. This file is for "the pieces snap together cleanly".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm_core.coordination import CompletionTracker, MessageBus, is_structured_payload
from swarm_core.experts.registry import ExpertProfile
from swarm_core.experts.suggest import TaskSimilarityStrategy
from swarm_core.models.completion import CompletionState
from swarm_core.skills.registry import Skill, SkillRegistry

from swarm_kb.completion_store import CompletionStore
from swarm_kb.debate_engine import DebateEngine
from swarm_kb.debate_formats import get_format, list_formats
from swarm_kb.dsl import (
    AtomNode, FlowExecution, FlowStore, GateNode, parse_flow,
)
from swarm_kb.judging import JudgingEngine
from swarm_kb.pgve import PgveStore
from swarm_kb.verification import VerificationStore


# ---------------------------------------------------------------------------
# Completion: full agent loop with subtasks + termination
# ---------------------------------------------------------------------------


def test_full_completion_loop_with_persistence_round_trip(tmp_path):
    """Agent does 3 subtasks, hits a think, recovers, completes -- all reloads."""
    # Pretend events.jsonl exists so events get mirrored.
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")

    store = CompletionStore(tmp_path, "sess-int-1")

    # Subtask 1
    rec = store.mark_subtask_done("scan", summary="scanned 12 files",
                                  outputs={"files": 12})
    assert rec.id == "scan"
    assert rec.loop_count == 1

    # Think a bit, then act
    assert store.record_think() == 1
    rec = store.mark_subtask_done("classify", summary="3 critical, 5 medium")
    assert store.state().consecutive_thinks == 0  # reset by subtask

    # Re-mark same subtask (legitimate retry)
    rec = store.mark_subtask_done("classify", summary="ignored summary")
    assert rec.loop_count == 2  # bumped, but original summary kept on storage
    assert "3 critical" in store.state().subtasks[1].summary

    # Complete
    store.complete_task("done with 8 findings", outputs={"count": 8})
    assert store.is_complete()
    assert store.should_stop() == (True, "completed")

    # Reload from disk -- everything must survive verbatim.
    fresh = CompletionStore(tmp_path, "sess-int-1")
    state = fresh.state()
    assert len(state.subtasks) == 2
    assert state.subtask_loop_counts["classify"] == 2
    assert state.completion.summary == "done with 8 findings"
    assert state.total_subtask_calls == 3

    # Events.jsonl should have 4 entries: 2 first-mark + 1 re-mark + 1 complete.
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    types = [json.loads(l)["event_type"] for l in lines]
    assert types.count("subtask_done") == 3
    assert types.count("task_completed") == 1


# ---------------------------------------------------------------------------
# Judging: 3 dimensions, 3 judges, synthesize
# ---------------------------------------------------------------------------


def test_full_judging_lifecycle_with_reload(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start(
        "Should we accept fix proposal fp-7c2a?",
        dimensions=["correctness", "regression_risk", "maintainability"],
        subject_kind="proposal",
        subject_ref="fp-7c2a",
    )

    eng.judge(j.id, judge="security", dimension="correctness",
              verdict="pass", rationale="addresses the auth bypass cleanly")
    eng.judge(j.id, judge="perf", dimension="regression_risk",
              verdict="mixed", rationale="adds 5ms per request -- tolerable")
    eng.judge(j.id, judge="design", dimension="maintainability",
              verdict="pass", rationale="reduces coupling between auth + session")

    intermediate = eng.get(j.id)
    assert intermediate.is_complete()  # all dimensions covered

    # Synthesise -- aggregator decides overall.
    synth = eng.synthesise(
        j.id,
        overall="pass",
        summary="net positive: cleaner code with acceptable perf cost",
        synthesised_by="orchestrator",
    )
    assert synth.dimensions["regression_risk"] == "mixed"

    # Reload via fresh engine.
    fresh = JudgingEngine(tmp_path)
    reloaded = fresh.get(j.id)
    assert reloaded.status == "resolved"
    assert reloaded.synthesis.overall == "pass"
    assert reloaded.synthesis.summary.startswith("net positive")


# ---------------------------------------------------------------------------
# Verification: aggregates evidence from multiple kinds incl. a judging
# ---------------------------------------------------------------------------


def test_verification_aggregates_multi_kind_evidence(tmp_path):
    judg_root = tmp_path / "judgings"
    verify_root = tmp_path / "verifications"

    # First, run a judging on the fix.
    judg = JudgingEngine(judg_root)
    j = judg.start("verify fp-x", dimensions=["test_coverage", "no_regression"])
    judg.judge(j.id, judge="qa", dimension="test_coverage",
               verdict="pass", rationale="3 new tests added")
    judg.judge(j.id, judge="qa", dimension="no_regression",
               verdict="pass", rationale="full suite green")
    judg.synthesise(j.id, overall="pass", summary="ready")

    # Now build a verification report that references the judging.
    verify = VerificationStore(verify_root)
    report = verify.start(fix_session="fix-int-1")

    verify.add_evidence(report.id, kind="test_diff",
                        summary="155 -> 158 passing",
                        data={"before": 155, "after": 158, "new": 3})
    verify.add_evidence(report.id, kind="quality_gate",
                        summary="gate=clean",
                        data={"recommendation": "stop_clean"})
    verify.add_evidence(report.id, kind="judging",
                        summary="qa council passed",
                        data={"judging_id": j.id, "overall": "pass"})

    verdict = verify.finalise(
        report.id,
        overall="pass",
        summary="three kinds of evidence all positive",
        synthesised_by="verify-orchestrator",
    )
    assert verdict.overall == "pass"

    # Reload and verify cross-references survive.
    fresh = VerificationStore(verify_root)
    reloaded = fresh.get(report.id)
    assert reloaded.status == "finalised"
    assert len(reloaded.evidence) == 3
    judging_evs = reloaded.evidence_by_kind("judging")
    assert len(judging_evs) == 1
    assert judging_evs[0].data["judging_id"] == j.id


# ---------------------------------------------------------------------------
# PGVE: full retry loop, revise -> revise -> accepted
# ---------------------------------------------------------------------------


def test_pgve_retry_then_accept(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="produce a fix for f-async-deadlock",
                    max_candidates=4)

    # Round 1: revise
    c1 = store.submit_candidate(s.id, generator="fix-1", content="patch v1")
    assert c1.previous_feedback == ""  # first candidate
    e1 = store.evaluate(s.id, evaluator="reviewer-1", verdict="revise",
                        feedback="missing lock release on exception path")
    assert store.get(s.id).status == "open"

    # Round 2: revise again
    c2 = store.submit_candidate(s.id, generator="fix-1", content="patch v2")
    assert c2.previous_feedback == "missing lock release on exception path"
    store.evaluate(s.id, evaluator="reviewer-1", verdict="revise",
                   feedback="now leaks file handle")

    # Round 3: accepted
    c3 = store.submit_candidate(s.id, generator="fix-1", content="patch v3")
    assert "leaks file handle" in c3.previous_feedback
    store.evaluate(s.id, evaluator="reviewer-1", verdict="accepted",
                   feedback="lgtm")

    final = store.get(s.id)
    assert final.status == "accepted"
    assert final.accepted_candidate_id == c3.id
    assert len(final.candidates) == 3
    assert len(final.evaluations) == 3

    # Reload survives.
    fresh = PgveStore(tmp_path)
    rl = fresh.get(s.id)
    assert rl.accepted_candidate_id == c3.id


def test_pgve_exhausts_budget(tmp_path):
    store = PgveStore(tmp_path)
    s = store.start(task_spec="t", max_candidates=2)
    store.submit_candidate(s.id, generator="g", content="v1")
    store.evaluate(s.id, evaluator="e", verdict="revise", feedback="more")
    store.submit_candidate(s.id, generator="g", content="v2")
    store.evaluate(s.id, evaluator="e", verdict="revise", feedback="still more")
    final = store.get(s.id)
    assert final.status == "exhausted"
    # Cannot submit anything more.
    with pytest.raises(ValueError, match="not open"):
        store.submit_candidate(s.id, generator="g", content="v3")


# ---------------------------------------------------------------------------
# DSL: full pipeline with parallel + gate + sequence
# ---------------------------------------------------------------------------


def test_dsl_full_flow_with_gate(tmp_path):
    src = "scan -> (lint, type_check) -> H -> review -> fix -> verify -> doc"
    store = FlowStore(tmp_path)
    flow = store.start(source=src,
                       known_names={"scan", "lint", "type_check", "review",
                                    "fix", "verify", "doc"})

    def step_named(flow_obj, name):
        for n in flow_obj.next_steps():
            if isinstance(n, AtomNode) and n.name == name:
                return n
        raise AssertionError(f"step {name!r} not pending")

    # Phase 1: scan (only)
    f = store.get(flow.id)
    assert {n.name for n in f.next_steps() if isinstance(n, AtomNode)} == {"scan"}
    store.mark_done(flow.id, step_named(f, "scan").id)

    # Phase 2: lint and type_check together
    f = store.get(flow.id)
    parallel_names = {n.name for n in f.next_steps() if isinstance(n, AtomNode)}
    assert parallel_names == {"lint", "type_check"}
    store.mark_done(flow.id, step_named(f, "type_check").id)
    store.mark_done(flow.id, step_named(f, "lint").id)

    # Phase 3: gate
    f = store.get(flow.id)
    pending = f.next_steps()
    assert len(pending) == 1
    assert isinstance(pending[0], GateNode)
    store.mark_done(flow.id, pending[0].id)

    # Phase 4-6: review, fix, verify in order
    for name in ("review", "fix", "verify"):
        f = store.get(flow.id)
        store.mark_done(flow.id, step_named(f, name).id)

    # Phase 7: doc -- the last
    f = store.get(flow.id)
    assert step_named(f, "doc").name == "doc"
    store.mark_done(flow.id, step_named(f, "doc").id)

    final = store.get(flow.id)
    assert final.status == "completed"
    assert final.next_steps() == []
    # Reload and confirm.
    fresh = FlowStore(tmp_path)
    rl = fresh.get(flow.id)
    assert rl.status == "completed"
    assert len(rl.completed) == 8  # scan + lint + type_check + H + review + fix + verify + doc


# ---------------------------------------------------------------------------
# Debate format: a trial with prosecution/defense/judge
# ---------------------------------------------------------------------------


def test_trial_format_runs_through_debate_engine(tmp_path):
    eng = DebateEngine(tmp_path)
    d = eng.start_debate(
        topic="Should we deprecate the legacy auth flow?",
        format="trial",
        context="Ref: f-7a91 -- session-token storage violates compliance.",
    )
    assert d.format == "trial"
    fmt = get_format("trial")
    assert {p.name for p in fmt.phases} == {"charge", "defense", "rebuttal", "ruling"}

    # Charge
    charge_id = eng.propose(
        d.id, author="prosecution",
        title="Deprecate legacy auth", description="Tokens stored insecurely.",
    )
    # Defense
    eng.critique(d.id, proposal_id=charge_id, critic="defense",
                 verdict="modify",
                 reasoning="Migration plan needed; not an instant deprecate.",
                 suggested_changes=["Add 6-month grace period"])
    # Ruling
    eng.vote(d.id, agent="judge", proposal_id=charge_id, support=True)
    result = eng.resolve(d.id)
    assert result["decision"]["chosen_proposal_id"] == charge_id

    # Reload via fresh engine.
    fresh = DebateEngine(tmp_path)
    reloaded = fresh.get_debate(d.id)
    assert reloaded.format == "trial"
    assert reloaded.status.value == "resolved"


def test_all_13_debate_formats_have_complete_phase_specs():
    """Every format must have actors, phases, stop_condition -- enterprise check."""
    for name in list_formats():
        fmt = get_format(name)
        d = fmt.to_dict()
        assert d["actors"], f"{name}: empty actors"
        assert d["phases"], f"{name}: empty phases"
        assert d["stop_condition"], f"{name}: empty stop_condition"
        for p in d["phases"]:
            assert p["actors"], f"{name}.{p['name']}: empty actors"
            assert p["description"], f"{name}.{p['name']}: empty description"


# ---------------------------------------------------------------------------
# Skill / expert routing: composes textmatch + suggest + recommend_for_task
# ---------------------------------------------------------------------------


def test_full_routing_picks_relevant_expert_and_skills(tmp_path):
    """Task description routes to the relevant expert AND filters skills."""
    # Stage 1: pick the right expert.
    profiles = [
        ExpertProfile(
            name="security-expert", description="finds auth bugs and injection vulnerabilities",
            source_file=Path("<sec>.yaml"),
            data={"system_prompt": "Audit for auth, injection, csrf, xss vectors."},
        ),
        ExpertProfile(
            name="perf-expert", description="finds slow queries and quadratic loops",
            source_file=Path("<perf>.yaml"),
            data={"system_prompt": "Profile for n+1 queries and cache misses."},
        ),
    ]
    strat = TaskSimilarityStrategy()
    ranked = strat.suggest(profiles, "audit auth bugs in the login flow")
    assert ranked[0]["slug"] == "<sec>"

    # Stage 2: with the selected expert's task, recommend skills.
    skills = [
        Skill(slug="systematic_debugging", name="Systematic Debugging",
              when_to_use="Use when investigating an auth or security bug",
              version="1", body="...", source_file=Path("<sd>"), universal=True),
        Skill(slug="brainstorming", name="Brainstorming",
              when_to_use="Use when generating ideas for a greenfield design",
              version="1", body="...", source_file=Path("<br>"), universal=True),
    ]
    reg = SkillRegistry()
    reg._cache = {s.slug: s for s in skills}  # noqa: SLF001 -- test fixture injection
    recs = reg.recommend_for_task("audit auth bugs in the login flow", min_score=0.05)
    rec_slugs = [s.slug for s, _ in recs]
    assert "systematic_debugging" in rec_slugs
    assert "brainstorming" not in rec_slugs


# ---------------------------------------------------------------------------
# MessageBus structured payloads -- subscriber resumes from one event
# ---------------------------------------------------------------------------


def test_structured_payload_carries_resumability_triple():
    bus = MessageBus()
    received = []
    bus.subscribe("review.next_file", received.append)

    bus.publish_structured(
        "review.next_file",
        content="Please review src/auth/login.py",
        background={
            "task": "security audit",
            "session_id": "sess-rev-1",
            "previous_files_done": ["src/auth/__init__.py"],
        },
        intermediate_output={
            "last_finding": "f-12ab",
            "running_count": 5,
        },
        from_agent="orchestrator",
        ts="2026-04-26T15:00:00Z",
    )
    assert len(received) == 1
    payload = received[0]
    assert is_structured_payload(payload)
    # A late-joining subscriber sees the WHOLE context in one payload.
    assert payload["background"]["task"] == "security audit"
    assert payload["intermediate_output"]["last_finding"] == "f-12ab"
    assert payload["from_agent"] == "orchestrator"


# ---------------------------------------------------------------------------
# Cross-module: PGVE candidate verified via Verification + Judging
# ---------------------------------------------------------------------------


def test_pgve_then_verification_then_judging_cross_links(tmp_path):
    """Candidate from pgve becomes subject of judging; both ref'd in a verification."""
    pgve_root = tmp_path / "pgve"
    judg_root = tmp_path / "judging"
    verify_root = tmp_path / "verify"

    # 1. PGVE proposes a fix candidate, accepted.
    pgve = PgveStore(pgve_root)
    p = pgve.start(task_spec="fix the data race in completion_store")
    cand = pgve.submit_candidate(p.id, generator="fix-expert",
                                 content="add file lock around persist()")
    pgve.evaluate(p.id, evaluator="self", verdict="accepted",
                  feedback="approved by initial review")

    # 2. Judging: did the council agree the fix is good?
    judg = JudgingEngine(judg_root)
    j = judg.start("evaluate accepted candidate", subject_kind="other",
                   subject_ref=cand.id, dimensions=["correctness", "perf_impact"])
    judg.judge(j.id, judge="threading", dimension="correctness",
               verdict="pass", rationale="lock acquisition is correct")
    judg.judge(j.id, judge="perf", dimension="perf_impact",
               verdict="mixed", rationale="2ms overhead under contention")
    judg.synthesise(j.id, overall="pass", summary="acceptable tradeoff")

    # 3. Verification: aggregate both into one report.
    verify = VerificationStore(verify_root)
    r = verify.start(fix_session="fix-cross-1")
    verify.add_evidence(r.id, kind="manual_note",
                        summary="pgve session closed with accepted candidate",
                        data={"pgve_id": p.id, "candidate_id": cand.id},
                        source_tool="fix")
    verify.add_evidence(r.id, kind="judging",
                        summary="council passed",
                        data={"judging_id": j.id, "overall": "pass"})
    verdict = verify.finalise(r.id, overall="pass",
                              summary="cross-checked from pgve + judging")

    # 4. Reload the verification and walk the chain back.
    fresh = VerificationStore(verify_root)
    rl = fresh.get(r.id)
    assert rl.verdict.overall == "pass"
    judging_data = rl.evidence_by_kind("judging")[0].data
    assert judging_data["judging_id"] == j.id

    # Walk to the judging.
    fresh_judg = JudgingEngine(judg_root)
    judg_loaded = fresh_judg.get(judging_data["judging_id"])
    assert judg_loaded.subject_ref == cand.id

    # Walk to the pgve and confirm the candidate referenced is the accepted one.
    fresh_pgve = PgveStore(pgve_root)
    p_loaded = fresh_pgve.get(p.id)
    assert p_loaded.accepted_candidate_id == cand.id


# ---------------------------------------------------------------------------
# Schema-versioning robustness: old data + unknown statuses load cleanly
# ---------------------------------------------------------------------------


def test_old_schema_versions_load_with_warnings(tmp_path, caplog):
    import logging

    # Plant a "future" judging file with unknown status + future schema_version.
    jid = "judg-future"
    jdir = tmp_path / jid
    jdir.mkdir()
    (jdir / "judging.json").write_text(json.dumps({
        "schema_version": 99,
        "id": jid,
        "subject": "from the future",
        "dimensions": ["a"],
        "judgments": [],
        "status": "kangaroo_court",  # unknown
    }), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        eng = JudgingEngine(tmp_path)
        loaded = eng.get(jid)

    assert loaded is not None
    assert loaded.status == "open"  # normalised
    # Warning should mention the unknown status.
    assert any("kangaroo_court" in r.message or "kangaroo_court" in str(r)
               for r in caplog.records)


def test_old_flow_with_unknown_status_normalises(tmp_path, caplog):
    import logging
    fid = "flow-old"
    fdir = tmp_path / fid
    fdir.mkdir()
    (fdir / "flow.json").write_text(json.dumps({
        "schema_version": 1,
        "id": fid,
        "source": "a -> b",
        "root": parse_flow("a -> b").to_dict(),
        "completed": [],
        "status": "weird",
    }), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        store = FlowStore(tmp_path)
        loaded = store.get(fid)
    assert loaded is not None
    assert loaded.status == "open"
    assert any("weird" in r.message or "weird" in str(r) for r in caplog.records)
