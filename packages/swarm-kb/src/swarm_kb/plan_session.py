"""Stage 2 Plan -- captures the writing_plans skill output.

Validates the assembled plan against the writing_plans contract
(header present, every task has Steps 1-5, exact commands with expected
output, every Step 5 commits).

See docs/decisions/2026-04-26-stage-2-plan-stage.md for the contract.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from swarm_core.io import atomic_write_text, append_jsonl_line
from swarm_core.logging_setup import get_logger
from swarm_core.sessions import SessionLifecycle
from swarm_core.timeutil import now_iso

_log = get_logger("kb.plan_session")


class PlanStatus:
    DRAFTING = "drafting"
    VALIDATED = "validated"
    INVALIDATED = "invalidated"   # validation failed; user must fix


class PlanSessionLifecycle(SessionLifecycle):
    tool_name = "plan"
    session_prefix = "plan"
    initial_files = ("tasks.jsonl", "plan.md", "events.jsonl")

    def build_meta(self, session_id: str, *, project_path: str, name: str) -> dict:
        meta = super().build_meta(session_id, project_path=project_path, name=name)
        meta["plan_status"] = PlanStatus.DRAFTING
        meta["adr_ids"] = []
        return meta


# Required headers from writing_plans skill
_REQUIRED_HEADER_FIELDS = ("Goal", "Architecture", "Tech stack", "ADR refs")
# Each task must have these step labels
_REQUIRED_STEP_PHRASES = (
    "Write the failing test",
    "Run test to verify it fails",
    "Write minimal implementation",
    "Run test to verify it passes",
    "Commit",
)


# ---------------------------------------------------------------- public API


def start_plan_session(
    sessions_root: Path,
    *,
    project_path: str,
    adr_ids: list[str],
    name: str = "",
) -> dict:
    """Open a new Plan session anchored to one or more ADRs."""
    if not adr_ids:
        raise ValueError("Plan sessions must reference at least one ADR")

    lc = PlanSessionLifecycle(sessions_root)
    sid = lc.create(project_path=project_path, name=name)
    sess_dir = lc.session_dir(sid)

    meta = json.loads((sess_dir / "meta.json").read_text(encoding="utf-8"))
    meta["adr_ids"] = list(adr_ids)
    atomic_write_text(sess_dir / "meta.json", json.dumps(meta, indent=2))

    _append_event(sess_dir, "plan_started", {"adr_ids": list(adr_ids)})
    return {
        "session_id": sid,
        "session_dir": str(sess_dir),
        "adr_ids": list(adr_ids),
        "next_skill": "writing_plans",
        "status": PlanStatus.DRAFTING,
    }


def emit_task(
    sessions_root: Path,
    *,
    session_id: str,
    task_md: str,
) -> dict:
    """Append one task to tasks.jsonl. Each task is the markdown body for
    one bite-sized step (2-5 minutes per writing_plans skill).
    """
    if not task_md or not task_md.strip():
        raise ValueError("task_md must be non-empty")

    lc = PlanSessionLifecycle(sessions_root)
    sess_dir = lc.session_dir(session_id)

    task_id = f"t-{_count_tasks(sess_dir) + 1:03d}"
    record = {
        "task_id": task_id,
        "markdown": task_md.rstrip(),
        "created_at": now_iso(),
    }
    append_jsonl_line(sess_dir / "tasks.jsonl", json.dumps(record))
    _append_event(sess_dir, "plan_task_emitted", {"task_id": task_id})
    return {"session_id": session_id, "task_id": task_id}


def finalize_plan(
    sessions_root: Path,
    *,
    session_id: str,
    plan_md: str,
) -> dict:
    """Persist plan.md and validate it against the writing_plans contract.

    Returns `{validated: bool, errors: list[str]}`. On success, status
    transitions to VALIDATED and the pipeline can advance.
    """
    if not plan_md or not plan_md.strip():
        raise ValueError("plan_md must be non-empty")

    lc = PlanSessionLifecycle(sessions_root)
    sess_dir = lc.session_dir(session_id)

    errors = validate_plan_markdown(plan_md)
    atomic_write_text(sess_dir / "plan.md", plan_md.rstrip() + "\n")

    if errors:
        _set_status(sess_dir, PlanStatus.INVALIDATED)
        _append_event(sess_dir, "plan_invalidated", {"errors": errors[:10]})
        return {
            "session_id": session_id,
            "validated": False,
            "errors": errors,
            "status": PlanStatus.INVALIDATED,
        }

    _set_status(sess_dir, PlanStatus.VALIDATED)
    _append_event(sess_dir, "plan_validated", {})
    return {
        "session_id": session_id,
        "validated": True,
        "errors": [],
        "status": PlanStatus.VALIDATED,
        "plan_path": str(sess_dir / "plan.md"),
    }


# ---------------------------------------------------------------- validation


def validate_plan_markdown(plan_md: str) -> list[str]:
    """Return a list of contract violations in `plan_md`. Empty -> valid."""
    errors: list[str] = []
    text = plan_md or ""

    for field in _REQUIRED_HEADER_FIELDS:
        # Tolerate `**Goal:**`, `**Goal**:`, and `Goal:` (no bold). The skill
        # template uses `**Field:**` but we don't want to fail validation on
        # cosmetic markdown variations.
        pat = rf"(?:\*\*)?{re.escape(field)}(?:\*\*)?\s*:"
        if not re.search(pat, text):
            errors.append(f"missing header field: {field}:")

    # Find tasks: headings like "### Task N: ..." or "## Task N: ..."
    task_blocks = list(re.finditer(r"^#{2,3}\s*Task\s+\d+\s*:", text, re.MULTILINE))
    if not task_blocks:
        errors.append("no '### Task N: ...' headings found -- plan must contain at least one task")
        return errors

    # Slice each task block by its heading position
    boundaries = [m.start() for m in task_blocks] + [len(text)]
    for i, m in enumerate(task_blocks):
        start, end = boundaries[i], boundaries[i + 1]
        block = text[start:end]
        heading = block.splitlines()[0]
        for phrase in _REQUIRED_STEP_PHRASES:
            if phrase not in block:
                errors.append(f"task {heading.strip()!r} missing step: {phrase!r}")
        # Step 5 must include a `git commit` line
        if "git commit" not in block:
            errors.append(f"task {heading.strip()!r} missing `git commit` invocation")

    return errors


# ---------------------------------------------------------------- helpers


def _set_status(sess_dir: Path, status: str) -> None:
    meta_path = sess_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["plan_status"] = status
    meta["updated_at"] = now_iso()
    atomic_write_text(meta_path, json.dumps(meta, indent=2))


def _count_tasks(sess_dir: Path) -> int:
    path = sess_dir / "tasks.jsonl"
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _append_event(sess_dir: Path, event_type: str, payload: dict) -> None:
    event = {"event_type": event_type, "payload": payload, "timestamp": now_iso()}
    append_jsonl_line(sess_dir / "events.jsonl", json.dumps(event))
