"""Lite-mode MCP-style tool functions -- escape hatches from the full pipeline.

These are the public functions the swarm-kb MCP server exposes as
`kb_quick_review` and `kb_quick_fix`. They wrap `lite_orchestration` with
input validation and persist results into the day-bucketed lite store.

Use cases:
  - One-off review of a single file ("can you skim src/auth.py and tell
    me what's obvious?") -- no full session, no cross-check, no claim.
  - Quick patch where the user already knows what's wrong -- propose +
    self-review + apply, without consensus rounds.

Heavyweight workflows (multi-expert, persistent sessions) still use the
full pipeline (`kb_start_pipeline`).
"""

from __future__ import annotations

from pathlib import Path

from .config import SuiteConfig
from .lite_orchestration import (
    LiteFinding,
    LiteFixProposal,
    record_lite_finding,
    record_lite_proposal,
)


def kb_quick_review(
    file: str,
    line_start: int,
    line_end: int,
    severity: str,
    title: str,
    expert_role: str,
    *,
    actual: str = "",
    expected: str = "",
    source_ref: str = "",
    confidence: float = 0.7,
    config: SuiteConfig | None = None,
) -> dict:
    """Post a single finding without opening a review session.

    Persisted under `~/.swarm-kb/lite/<YYYY-MM-DD>/lite-findings.jsonl`
    so it can be promoted into a full session later if the work grows.
    """
    if line_start <= 0 or line_end < line_start:
        raise ValueError(f"invalid line range: {line_start}..{line_end}")
    if severity not in {"critical", "high", "medium", "low", "info"}:
        raise ValueError(f"invalid severity: {severity!r}")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be in [0, 1]: {confidence}")

    cfg = config or SuiteConfig.load()
    finding = LiteFinding(
        file=file, line_start=line_start, line_end=line_end,
        severity=severity, title=title, expert_role=expert_role,
        actual=actual, expected=expected, source_ref=source_ref,
        confidence=confidence,
    )
    fid = record_lite_finding(cfg.kb_root, finding)
    return {
        "id": fid,
        "stored_in": "lite",
        "promote_with": "kb_promote_to_review_session(lite_finding_id=...)",
        "finding": finding.to_dict(),
    }


def kb_quick_fix(
    file: str,
    line_start: int,
    line_end: int,
    old_text: str,
    new_text: str,
    rationale: str,
    expert_role: str,
    *,
    finding_id: str = "",
    config: SuiteConfig | None = None,
) -> dict:
    """Record a one-shot fix proposal without opening a fix session.

    The patch is NOT applied here -- the caller (or a downstream tool)
    actually edits the file. This function only records intent so the
    operation shows up in `~/.swarm-kb/lite/...` for audit and so the
    `self_review` skill can validate the patch before application.
    """
    if line_start <= 0 or line_end < line_start:
        raise ValueError(f"invalid line range: {line_start}..{line_end}")
    if not new_text and old_text:
        raise ValueError("new_text cannot be empty for a non-deletion patch")
    if not rationale.strip():
        raise ValueError("rationale must explain WHY this patch fixes the issue")

    cfg = config or SuiteConfig.load()
    proposal = LiteFixProposal(
        file=file, line_start=line_start, line_end=line_end,
        old_text=old_text, new_text=new_text, rationale=rationale,
        expert_role=expert_role, finding_id=finding_id,
    )
    pid = record_lite_proposal(cfg.kb_root, proposal)
    return {
        "id": pid,
        "stored_in": "lite",
        "next_step": "Apply the patch with your editor / Edit tool, then verify with the project's test command.",
        "proposal": proposal.to_dict(),
    }
