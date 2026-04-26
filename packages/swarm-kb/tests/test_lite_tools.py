"""Tests for kb_quick_review / kb_quick_fix."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swarm_kb.config import SuiteConfig
from swarm_kb.lite_tools import kb_quick_review, kb_quick_fix


def _cfg(tmp_path: Path) -> SuiteConfig:
    return SuiteConfig(storage_root=str(tmp_path))


def test_quick_review_persists_finding(tmp_path: Path):
    cfg = _cfg(tmp_path)
    out = kb_quick_review(
        file="src/auth.py", line_start=12, line_end=14,
        severity="high", title="SQL injection",
        expert_role="security-surface",
        actual="user input concatenated into query",
        expected="parameterized query",
        source_ref="src/auth.py:12",
        config=cfg,
    )
    assert out["id"].startswith("lf-")
    # Find the recorded JSONL
    today_dirs = list((tmp_path / "lite").iterdir())
    assert len(today_dirs) == 1
    jsonl = today_dirs[0] / "lite-findings.jsonl"
    line = jsonl.read_text(encoding="utf-8").strip()
    record = json.loads(line)
    assert record["title"] == "SQL injection"
    assert record["severity"] == "high"
    assert record["lite"] is True


def test_quick_review_validates_severity(tmp_path: Path):
    cfg = _cfg(tmp_path)
    with pytest.raises(ValueError):
        kb_quick_review(file="x.py", line_start=1, line_end=1,
                        severity="bogus", title="t", expert_role="r", config=cfg)


def test_quick_review_validates_line_range(tmp_path: Path):
    cfg = _cfg(tmp_path)
    with pytest.raises(ValueError):
        kb_quick_review(file="x.py", line_start=10, line_end=5,
                        severity="low", title="t", expert_role="r", config=cfg)


def test_quick_fix_persists_proposal(tmp_path: Path):
    cfg = _cfg(tmp_path)
    out = kb_quick_fix(
        file="src/auth.py", line_start=12, line_end=12,
        old_text='execute(f"... {x}")', new_text='execute("... ?", (x,))',
        rationale="Parameterize the query to prevent injection.",
        expert_role="security-fix",
        config=cfg,
    )
    assert out["id"].startswith("lp-")
    today_dirs = list((tmp_path / "lite").iterdir())
    jsonl = today_dirs[0] / "lite-proposals.jsonl"
    record = json.loads(jsonl.read_text(encoding="utf-8").strip())
    assert "Parameterize" in record["rationale"]
    assert record["lite"] is True


def test_quick_fix_requires_rationale(tmp_path: Path):
    cfg = _cfg(tmp_path)
    with pytest.raises(ValueError):
        kb_quick_fix(file="x.py", line_start=1, line_end=1,
                     old_text="a", new_text="b", rationale="   ",
                     expert_role="r", config=cfg)
