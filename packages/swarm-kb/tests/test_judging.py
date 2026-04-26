"""Tests for CouncilAsAJudge -- multi-dimensional judging engine."""

from __future__ import annotations

import json

import pytest

from swarm_kb.judging import (
    DEFAULT_DIMENSIONS,
    Judging,
    JudgingEngine,
    Judgment,
    JudgingSynthesis,
)


def test_judgment_validates_verdict():
    with pytest.raises(ValueError, match="not in"):
        Judgment(judge="a", dimension="accuracy", verdict="excellent")


def test_judging_requires_dimensions():
    with pytest.raises(ValueError, match="at least one"):
        Judging(subject="x", dimensions=[])


def test_engine_starts_judging_with_default_dimensions(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("Is the security finding valid?")
    assert j.subject == "Is the security finding valid?"
    assert j.dimensions == list(DEFAULT_DIMENSIONS)
    assert j.status == "open"
    # Persisted to disk.
    path = tmp_path / j.id / "judging.json"
    assert path.exists()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["id"] == j.id
    assert raw["schema_version"] == 1


def test_engine_starts_with_custom_dimensions(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("review a fix", dimensions=["correctness", "regression_risk"])
    assert j.dimensions == ["correctness", "regression_risk"]


def test_engine_subject_required(tmp_path):
    eng = JudgingEngine(tmp_path)
    with pytest.raises(ValueError, match="non-empty"):
        eng.start("")


def test_engine_judge_submission_persists(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("subject", dimensions=["a", "b"])
    jid = eng.judge(
        j.id,
        judge="critic-1",
        dimension="a",
        verdict="pass",
        rationale="meets the bar",
    )
    assert jid.startswith("jdg-")
    reloaded = eng.get(j.id)
    assert reloaded is not None
    assert len(reloaded.judgments) == 1
    assert reloaded.judgments[0].dimension == "a"
    assert reloaded.judgments[0].verdict == "pass"


def test_engine_re_judge_overwrites_per_judge_dimension(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("subject", dimensions=["a"])
    eng.judge(j.id, judge="critic-1", dimension="a", verdict="pass", rationale="r1")
    eng.judge(j.id, judge="critic-1", dimension="a", verdict="fail", rationale="r2")
    reloaded = eng.get(j.id)
    assert len(reloaded.judgments) == 1
    assert reloaded.judgments[0].verdict == "fail"
    assert reloaded.judgments[0].rationale == "r2"


def test_engine_two_judges_same_dimension_kept(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("subject", dimensions=["a"])
    eng.judge(j.id, judge="critic-1", dimension="a", verdict="pass", rationale="r1")
    eng.judge(j.id, judge="critic-2", dimension="a", verdict="fail", rationale="r2")
    reloaded = eng.get(j.id)
    assert len(reloaded.judgments) == 2


def test_engine_unknown_dimension_rejected(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("subject", dimensions=["a"])
    with pytest.raises(ValueError, match="not in"):
        eng.judge(j.id, judge="x", dimension="zzz", verdict="pass", rationale="r")


def test_engine_resolve_synthesises(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("subject", dimensions=["a", "b"])
    eng.judge(j.id, judge="c1", dimension="a", verdict="pass", rationale="r1")
    eng.judge(j.id, judge="c2", dimension="b", verdict="fail", rationale="r2")
    synth = eng.synthesise(
        j.id,
        overall="mixed",
        summary="a is fine, b needs work",
        synthesised_by="aggregator",
    )
    assert synth.overall == "mixed"
    assert synth.dimensions == {"a": "pass", "b": "fail"}
    reloaded = eng.get(j.id)
    assert reloaded.status == "resolved"


def test_engine_resolve_with_explicit_dim_verdicts(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("subject", dimensions=["a", "b"])
    synth = eng.synthesise(
        j.id,
        overall="pass",
        summary="ok",
        dimensions={"a": "pass", "b": "pass"},
    )
    assert synth.dimensions == {"a": "pass", "b": "pass"}


def test_engine_resolve_overall_invalid_raises(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("subject", dimensions=["a"])
    with pytest.raises(ValueError, match="not in"):
        eng.synthesise(j.id, overall="excellent", summary="x")


def test_engine_resolve_when_closed_raises(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("subject", dimensions=["a"])
    eng.synthesise(j.id, overall="pass", summary="ok")
    with pytest.raises(ValueError, match="not open"):
        eng.synthesise(j.id, overall="fail", summary="oops")


def test_engine_judge_after_resolve_raises(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("subject", dimensions=["a"])
    eng.synthesise(j.id, overall="pass", summary="ok")
    with pytest.raises(ValueError, match="not open"):
        eng.judge(j.id, judge="x", dimension="a", verdict="pass", rationale="r")


def test_engine_cancel(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("subject", dimensions=["a"])
    eng.cancel(j.id)
    reloaded = eng.get(j.id)
    assert reloaded.status == "cancelled"


def test_engine_list_filters_by_status(tmp_path):
    eng = JudgingEngine(tmp_path)
    j1 = eng.start("s1", dimensions=["a"])
    j2 = eng.start("s2", dimensions=["a"])
    eng.synthesise(j2.id, overall="pass", summary="ok")
    open_only = eng.list_all(status="open")
    resolved_only = eng.list_all(status="resolved")
    assert {x.id for x in open_only} == {j1.id}
    assert {x.id for x in resolved_only} == {j2.id}


def test_engine_round_trip_via_disk(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("s", dimensions=["a", "b"])
    eng.judge(j.id, judge="c1", dimension="a", verdict="pass", rationale="r1")
    eng.synthesise(j.id, overall="pass", summary="ok")

    # Fresh engine over same dir reloads everything.
    eng2 = JudgingEngine(tmp_path)
    reloaded = eng2.get(j.id)
    assert reloaded.subject == "s"
    assert reloaded.status == "resolved"
    assert reloaded.synthesis.overall == "pass"


def test_judging_is_complete_when_every_dimension_judged(tmp_path):
    eng = JudgingEngine(tmp_path)
    j = eng.start("s", dimensions=["a", "b"])
    eng.judge(j.id, judge="c1", dimension="a", verdict="pass", rationale="r")
    assert not eng.get(j.id).is_complete()
    eng.judge(j.id, judge="c2", dimension="b", verdict="pass", rationale="r")
    assert eng.get(j.id).is_complete()


def test_judging_subject_kind_validated():
    with pytest.raises(ValueError, match="not in"):
        Judging(subject="x", dimensions=["a"], subject_kind="fiding")


def test_judging_subject_kind_other_accepted():
    # 'other' is the documented escape hatch.
    j = Judging(subject="x", dimensions=["a"], subject_kind="other")
    assert j.subject_kind == "other"
