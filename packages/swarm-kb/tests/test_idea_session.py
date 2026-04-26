"""Tests for the Stage 0a Idea session."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swarm_kb.idea_session import (
    IdeaStatus,
    start_idea_session,
    capture_idea_answer,
    record_alternatives,
    finalize_idea_design,
)


def test_start_creates_session_with_brainstorming_handoff(tmp_path: Path):
    out = start_idea_session(tmp_path, project_path="/proj", prompt="CSV to Parquet CLI")
    assert out["status"] == IdeaStatus.GATHERING
    assert out["next_skill"] == "brainstorming"
    assert "Phase 1" in out["next_phase"]

    sess_dir = Path(out["session_dir"])
    meta = json.loads((sess_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["prompt"] == "CSV to Parquet CLI"
    assert meta["idea_status"] == IdeaStatus.GATHERING


def test_capture_answer_appends(tmp_path: Path):
    sid = start_idea_session(tmp_path, project_path="/p", prompt="x")["session_id"]
    capture_idea_answer(tmp_path, session_id=sid, question="streaming or batch?", answer="batch")
    capture_idea_answer(tmp_path, session_id=sid, question="schema?", answer="explicit")

    answers = (tmp_path / sid / "answers.md").read_text(encoding="utf-8")
    assert "streaming or batch?" in answers
    assert "batch" in answers
    assert "schema?" in answers
    assert "explicit" in answers


def test_record_alternatives_requires_at_least_two(tmp_path: Path):
    sid = start_idea_session(tmp_path, project_path="/p", prompt="x")["session_id"]
    with pytest.raises(ValueError):
        record_alternatives(tmp_path, session_id=sid, alternatives=[{"id": "a", "title": "A"}])


def test_record_alternatives_marks_chosen(tmp_path: Path):
    sid = start_idea_session(tmp_path, project_path="/p", prompt="x")["session_id"]
    out = record_alternatives(tmp_path, session_id=sid, alternatives=[
        {"id": "a", "title": "Stream-based", "architecture": "iter()", "trade_offs": "low memory"},
        {"id": "b", "title": "Batch-based", "architecture": "load all", "trade_offs": "fast for small inputs"},
    ], chosen_id="b")
    assert out["chosen_id"] == "b"
    assert out["status"] == IdeaStatus.DESIGNING
    body = (tmp_path / sid / "alternatives.md").read_text(encoding="utf-8")
    assert "Batch-based (chosen)" in body
    assert "Stream-based" in body  # without chosen marker


def test_finalize_marks_design_approved(tmp_path: Path):
    sid = start_idea_session(tmp_path, project_path="/p", prompt="x")["session_id"]
    out = finalize_idea_design(tmp_path, session_id=sid, design_md="# Design\nDetails.")
    assert out["status"] == IdeaStatus.DESIGN_APPROVED
    assert out["ready_to_advance"]
    meta = json.loads((tmp_path / sid / "meta.json").read_text(encoding="utf-8"))
    assert meta["idea_status"] == IdeaStatus.DESIGN_APPROVED


def test_finalize_rejects_empty(tmp_path: Path):
    sid = start_idea_session(tmp_path, project_path="/p", prompt="x")["session_id"]
    with pytest.raises(ValueError):
        finalize_idea_design(tmp_path, session_id=sid, design_md="")
