"""Tests for Pipeline.rewind_to / PipelineManager.rewind."""

import sys
from pathlib import Path

import pytest

# Allow swarm-kb to be imported without an editable install (matches the
# pattern used elsewhere in this repo for cross-package testing).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swarm_kb.pipeline import Pipeline, PipelineManager, STAGE_ORDER, StageStatus


def test_rewind_to_earlier_stage(tmp_path: Path):
    p = Pipeline(project_path=str(tmp_path))
    p.advance()  # spec -> arch
    p.advance()  # arch -> review
    assert p.current_stage == "review"

    ok = p.rewind_to("arch", reason="ADR was wrong")
    assert ok
    assert p.current_stage == "arch"
    assert p.stages["arch"].status == StageStatus.ACTIVE
    assert p.stages["review"].status == StageStatus.PENDING
    assert "ADR was wrong" in p.stages["arch"].notes
    assert "rewound from review" in p.stages["arch"].notes


def test_rewind_to_invalid_stage(tmp_path: Path):
    p = Pipeline(project_path=str(tmp_path))
    p.advance()
    assert p.rewind_to("nonexistent") is False


def test_rewind_must_be_strictly_backward(tmp_path: Path):
    p = Pipeline(project_path=str(tmp_path))
    # current is "spec"; rewinding to "spec" or any later stage must fail
    assert p.rewind_to("spec") is False
    assert p.rewind_to("review") is False


def test_rewind_resets_intermediate_stages_to_pending(tmp_path: Path):
    p = Pipeline(project_path=str(tmp_path))
    p.advance()  # arch
    p.advance()  # review
    p.advance()  # fix
    assert p.current_stage == "fix"

    ok = p.rewind_to("arch")
    assert ok
    assert p.stages["arch"].status == StageStatus.ACTIVE
    assert p.stages["review"].status == StageStatus.PENDING
    assert p.stages["fix"].status == StageStatus.PENDING


def test_pipeline_manager_rewind(tmp_path: Path):
    mgr = PipelineManager(tmp_path)
    pipe = mgr.start("/some/proj")
    mgr.advance(pipe.id)  # arch
    mgr.advance(pipe.id)  # review

    result = mgr.rewind(pipe.id, "arch", reason="missing constraint")
    assert result["status"] == "rewound"
    assert result["current_stage"] == "arch"
    assert result["reason"] == "missing constraint"


def test_pipeline_manager_rewind_invalid(tmp_path: Path):
    mgr = PipelineManager(tmp_path)
    pipe = mgr.start("/some/proj")
    # current is spec; cannot rewind anywhere
    result = mgr.rewind(pipe.id, "arch")
    assert "error" in result
