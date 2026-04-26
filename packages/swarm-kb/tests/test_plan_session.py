"""Tests for the Stage 2 Plan session + writing_plans validator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swarm_kb.plan_session import (
    PlanStatus,
    start_plan_session,
    emit_task,
    finalize_plan,
    validate_plan_markdown,
)


_VALID_PLAN = """# Auth Module Implementation Plan

> **For the executing agent:** apply the writing_plans skill.

**Goal:** Add auth.

**Architecture:** Use OAuth2.

**Tech stack:** Python, requests.

**ADR refs:** adr-001

---

### Task 1: Token validator

**Files:**
- Create: `src/auth.py`
- Test: `tests/test_auth.py`

**Step 1: Write the failing test**

```python
def test_validate(): ...
```

**Step 2: Run test to verify it fails**

Run: `pytest -k validate`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
def validate(): pass
```

**Step 4: Run test to verify it passes**

Run: `pytest -k validate`
Expected: PASS

**Step 5: Commit**

```bash
git add src/auth.py
git commit -m "feat: add validator"
```
"""


def test_start_requires_adr_ids(tmp_path: Path):
    with pytest.raises(ValueError):
        start_plan_session(tmp_path, project_path="/p", adr_ids=[])


def test_start_records_adrs(tmp_path: Path):
    out = start_plan_session(tmp_path, project_path="/p", adr_ids=["adr-1", "adr-2"])
    assert out["adr_ids"] == ["adr-1", "adr-2"]
    assert out["status"] == PlanStatus.DRAFTING


def test_emit_task_assigns_sequential_ids(tmp_path: Path):
    sid = start_plan_session(tmp_path, project_path="/p", adr_ids=["a"])["session_id"]
    a = emit_task(tmp_path, session_id=sid, task_md="### Task 1: foo\n...")
    b = emit_task(tmp_path, session_id=sid, task_md="### Task 2: bar\n...")
    assert a["task_id"] == "t-001"
    assert b["task_id"] == "t-002"


def test_validate_catches_missing_header():
    errors = validate_plan_markdown("### Task 1: foo\n\nstep 1: write\n...\n")
    assert any("missing header field" in e for e in errors)


def test_validate_catches_no_tasks():
    errors = validate_plan_markdown(
        "**Goal:** x\n**Architecture:** x\n**Tech stack:** x\n**ADR refs:** x"
    )
    assert any("no '### Task" in e for e in errors)


def test_validate_catches_missing_step():
    incomplete = _VALID_PLAN.replace("Run test to verify it passes", "different text")
    errors = validate_plan_markdown(incomplete)
    assert any("Run test to verify it passes" in e for e in errors)


def test_valid_plan_passes_validator():
    errors = validate_plan_markdown(_VALID_PLAN)
    assert errors == [], errors


def test_finalize_validates(tmp_path: Path):
    sid = start_plan_session(tmp_path, project_path="/p", adr_ids=["a"])["session_id"]
    out = finalize_plan(tmp_path, session_id=sid, plan_md=_VALID_PLAN)
    assert out["validated"]
    assert out["status"] == PlanStatus.VALIDATED


def test_finalize_invalid_returns_errors(tmp_path: Path):
    sid = start_plan_session(tmp_path, project_path="/p", adr_ids=["a"])["session_id"]
    out = finalize_plan(tmp_path, session_id=sid, plan_md="# Bad plan with no header")
    assert not out["validated"]
    assert out["errors"]
    assert out["status"] == PlanStatus.INVALIDATED
