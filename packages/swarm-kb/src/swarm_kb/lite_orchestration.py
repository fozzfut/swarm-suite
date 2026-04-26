"""Lite-mode orchestrators -- escape hatches from the full pipeline.

The standard Swarm Suite pipeline (Spec -> Arch -> Review -> Fix -> Doc) is
optimized for industrial-grade work on substantial codebases. For one-shot
fixes and quick reviews, the ceremony is overkill. Lite-mode skips:
  - claim/release dance (single expert -> no claim collisions)
  - cross-check phase (single expert -> nobody to cross-check)
  - full session lifecycle (no meta.json, no events.jsonl)

Lite-mode results are still persisted (in `<kb>/lite/<date>/`) so they can
be promoted into a full session later if the work grows.

This module provides the abstractions; tool packages (`review-swarm`,
`fix-swarm`) wire them into MCP tools (`kb_quick_review`, `kb_quick_fix`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from swarm_core.ids import generate_id
from swarm_core.io import append_jsonl_line, atomic_write_text
from swarm_core.timeutil import now_iso
from swarm_core.logging_setup import get_logger

_log = get_logger("kb.lite_orchestration")


@dataclass
class LiteFinding:
    """Minimal finding shape for quick_review.

    No `session_id` -- lite-mode findings are per-call, not per-session.
    `expert_role` is required so the user can see which expert produced
    the finding even without a session.
    """
    file: str
    line_start: int
    line_end: int
    severity: str
    title: str
    expert_role: str
    actual: str = ""
    expected: str = ""
    source_ref: str = ""
    confidence: float = 0.7
    id: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            # length=4 -> 32-bit suffix (~4B states); birthday threshold ~65k.
            # Lite-mode runs 100s of times per day across users; length=2
            # (16-bit) gave a 0.7% collision rate at 1000 generations.
            self.id = generate_id("lf", length=4)  # "lite finding"
        if not self.created_at:
            self.created_at = now_iso()

    def to_dict(self) -> dict:
        return {
            "id": self.id, "file": self.file,
            "line_start": self.line_start, "line_end": self.line_end,
            "severity": self.severity, "title": self.title,
            "expert_role": self.expert_role,
            "actual": self.actual, "expected": self.expected,
            "source_ref": self.source_ref, "confidence": self.confidence,
            "created_at": self.created_at, "lite": True,
            "schema_version": 1,
        }


@dataclass
class LiteFixProposal:
    """Minimal fix proposal for quick_fix."""
    file: str
    line_start: int
    line_end: int
    old_text: str
    new_text: str
    rationale: str
    expert_role: str
    finding_id: str = ""  # optional -- may not have a corresponding finding
    id: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            # See LiteFinding.__post_init__ for length rationale (32-bit).
            self.id = generate_id("lp", length=4)  # "lite proposal"
        if not self.created_at:
            self.created_at = now_iso()

    def to_dict(self) -> dict:
        return {
            "id": self.id, "file": self.file,
            "line_start": self.line_start, "line_end": self.line_end,
            "old_text": self.old_text, "new_text": self.new_text,
            "rationale": self.rationale, "expert_role": self.expert_role,
            "finding_id": self.finding_id, "created_at": self.created_at,
            "lite": True,
            "schema_version": 1,
        }


def lite_dir(kb_root: Path, *, today: str | None = None) -> Path:
    """Day-bucketed dir under <kb>/lite/YYYY-MM-DD/. Created on demand."""
    today = today or now_iso()[:10]
    d = Path(kb_root) / "lite" / today
    d.mkdir(parents=True, exist_ok=True)
    return d


def record_lite_finding(kb_root: Path, finding: LiteFinding) -> str:
    """Append a lite finding to the day-bucket lite-findings.jsonl."""
    import json
    d = lite_dir(kb_root)
    append_jsonl_line(d / "lite-findings.jsonl", json.dumps(finding.to_dict()))
    return finding.id


def record_lite_proposal(kb_root: Path, proposal: LiteFixProposal) -> str:
    """Append a lite proposal to the day-bucket lite-proposals.jsonl."""
    import json
    d = lite_dir(kb_root)
    append_jsonl_line(d / "lite-proposals.jsonl", json.dumps(proposal.to_dict()))
    return proposal.id


def write_lite_summary(kb_root: Path, content: str, *, name: str = "summary.md") -> Path:
    """Persist a one-shot summary doc into the day bucket."""
    path = lite_dir(kb_root) / name
    atomic_write_text(path, content)
    return path
