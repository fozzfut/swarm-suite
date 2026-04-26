"""Tests for VerificationReport / VerificationStore."""

from __future__ import annotations

import json

import pytest

from swarm_kb.verification import (
    VALID_EVIDENCE_KINDS,
    VALID_VERDICTS,
    VerificationEvidence,
    VerificationReport,
    VerificationStore,
    VerificationVerdict,
)


def test_evidence_kind_validated():
    with pytest.raises(ValueError, match="not in"):
        VerificationEvidence(kind="not_a_kind")


def test_verdict_validated():
    with pytest.raises(ValueError, match="not in"):
        VerificationVerdict(overall="excellent")


def test_store_start_persists(tmp_path):
    store = VerificationStore(tmp_path)
    r = store.start(fix_session="fix-1", project_path="/x")
    path = tmp_path / r.id / "verification.json"
    assert path.exists()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["fix_session"] == "fix-1"
    assert raw["status"] == "open"
    assert raw["schema_version"] == 1


def test_store_requires_fix_session(tmp_path):
    store = VerificationStore(tmp_path)
    with pytest.raises(ValueError, match="non-empty"):
        store.start(fix_session="")


def test_add_evidence_persists(tmp_path):
    store = VerificationStore(tmp_path)
    r = store.start(fix_session="fix-1")
    ev_id = store.add_evidence(
        r.id,
        kind="test_diff",
        summary="3 new tests passing",
        data={"before": 100, "after": 103},
    )
    assert ev_id.startswith("ev-")
    reloaded = store.get(r.id)
    assert len(reloaded.evidence) == 1
    assert reloaded.evidence[0].kind == "test_diff"
    assert reloaded.evidence[0].data == {"before": 100, "after": 103}


def test_add_evidence_unknown_kind_rejected(tmp_path):
    store = VerificationStore(tmp_path)
    r = store.start(fix_session="fix-1")
    with pytest.raises(ValueError, match="not in"):
        store.add_evidence(r.id, kind="weird", summary="x")


def test_finalise_records_verdict(tmp_path):
    store = VerificationStore(tmp_path)
    r = store.start(fix_session="fix-1")
    store.add_evidence(r.id, kind="quality_gate", summary="passed")
    verdict = store.finalise(
        r.id,
        overall="pass",
        summary="all evidence pass",
        synthesised_by="orchestrator",
    )
    assert verdict.overall == "pass"
    reloaded = store.get(r.id)
    assert reloaded.status == "finalised"
    assert reloaded.verdict.summary == "all evidence pass"


def test_finalise_when_closed_raises(tmp_path):
    store = VerificationStore(tmp_path)
    r = store.start(fix_session="fix-1")
    store.finalise(r.id, overall="pass", summary="ok")
    with pytest.raises(ValueError, match="not open"):
        store.finalise(r.id, overall="fail", summary="oops")


def test_add_evidence_after_finalise_raises(tmp_path):
    store = VerificationStore(tmp_path)
    r = store.start(fix_session="fix-1")
    store.finalise(r.id, overall="pass", summary="ok")
    with pytest.raises(ValueError, match="not open"):
        store.add_evidence(r.id, kind="manual_note", summary="late note")


def test_cancel(tmp_path):
    store = VerificationStore(tmp_path)
    r = store.start(fix_session="fix-1")
    store.cancel(r.id)
    reloaded = store.get(r.id)
    assert reloaded.status == "cancelled"


def test_list_filters_by_status_and_fix_session(tmp_path):
    store = VerificationStore(tmp_path)
    r1 = store.start(fix_session="fix-1")
    r2 = store.start(fix_session="fix-2")
    store.finalise(r2.id, overall="pass", summary="ok")
    open_only = store.list_all(status="open")
    finalised_only = store.list_all(status="finalised")
    fix_1_only = store.list_all(fix_session="fix-1")
    assert {r.id for r in open_only} == {r1.id}
    assert {r.id for r in finalised_only} == {r2.id}
    assert {r.id for r in fix_1_only} == {r1.id}


def test_round_trip_via_disk(tmp_path):
    store = VerificationStore(tmp_path)
    r = store.start(fix_session="fix-x", project_path="/p")
    store.add_evidence(r.id, kind="judging", summary="from council",
                       data={"judging_id": "judg-abc"})
    store.finalise(r.id, overall="partial", summary="needs follow-up",
                   follow_ups=["docs need update"])

    fresh = VerificationStore(tmp_path)
    reloaded = fresh.get(r.id)
    assert reloaded.fix_session == "fix-x"
    assert reloaded.status == "finalised"
    assert reloaded.verdict.overall == "partial"
    assert reloaded.verdict.follow_ups == ["docs need update"]


def test_evidence_by_kind_filter(tmp_path):
    store = VerificationStore(tmp_path)
    r = store.start(fix_session="fix-1")
    store.add_evidence(r.id, kind="test_diff", summary="t1")
    store.add_evidence(r.id, kind="quality_gate", summary="qg")
    store.add_evidence(r.id, kind="test_diff", summary="t2")
    reloaded = store.get(r.id)
    test_evs = reloaded.evidence_by_kind("test_diff")
    assert len(test_evs) == 2
    assert reloaded.evidence_by_kind("regression_scan") == []


def test_valid_verdicts_constant():
    assert "pass" in VALID_VERDICTS
    assert "fail" in VALID_VERDICTS
    assert "partial" in VALID_VERDICTS


def test_valid_evidence_kinds_constant():
    assert "test_diff" in VALID_EVIDENCE_KINDS
    assert "quality_gate" in VALID_EVIDENCE_KINDS
    assert "judging" in VALID_EVIDENCE_KINDS
