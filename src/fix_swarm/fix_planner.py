"""Generate a FixPlan from parsed findings by reading actual source files."""

from __future__ import annotations

from pathlib import Path

from .models import FixAction, FixActionType, FixPlan
from .report_parser import ParsedFinding


class OverlapError(Exception):
    """Raised when two fix actions overlap in the same file."""


def build_plan(
    findings: list[ParsedFinding],
    base_dir: str | Path = ".",
) -> FixPlan:
    """Create a FixPlan from parsed findings.

    For each finding that has a concrete suggestion (action == 'fix'),
    generate a FixAction by reading the relevant lines from the source file.

    Findings with action 'investigate', 'document', or 'ignore' are skipped
    because they do not map to concrete text replacements.
    """
    base = Path(base_dir)
    actions: list[FixAction] = []

    for finding in findings:
        # Only 'fix' suggestions become concrete actions
        if finding.suggestion_action != "fix":
            continue

        source_path = base / finding.file
        if not source_path.is_file():
            continue

        try:
            text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.splitlines(keepends=True)

        # Clamp line range to file bounds (1-indexed in findings)
        start = max(1, finding.line_start)
        end = min(len(lines), finding.line_end)
        if start > len(lines):
            continue

        old_text = "".join(lines[start - 1 : end])

        # Build the new_text from the suggestion_detail.
        # Only concrete code from suggestion_detail is safe to use;
        # finding.expected is natural language and must not be injected.
        new_text = finding.suggestion_detail or ""

        if not new_text:
            # Nothing concrete to replace with -- skip.
            continue

        # Determine action type
        if not new_text.strip():
            action_type = FixActionType.DELETE
        elif not old_text.strip():
            action_type = FixActionType.INSERT
        else:
            action_type = FixActionType.REPLACE

        actions.append(FixAction(
            finding_id=finding.id,
            file=finding.file,
            line_start=start,
            line_end=end,
            action=action_type,
            old_text=old_text,
            new_text=new_text,
            rationale=finding.title or finding.actual,
        ))

    plan = FixPlan(actions=actions)
    _validate_no_overlaps(plan)
    return plan


def _validate_no_overlaps(plan: FixPlan) -> None:
    """Raise OverlapError if any two actions in the same file have overlapping line ranges."""
    for file_path in plan.files():
        file_actions = sorted(
            [a for a in plan.actions if a.file == file_path],
            key=lambda a: a.line_start,
        )
        for i in range(len(file_actions) - 1):
            current = file_actions[i]
            nxt = file_actions[i + 1]
            if current.line_end >= nxt.line_start:
                raise OverlapError(
                    f"Overlapping fixes in {file_path}: "
                    f"{current.finding_id} (L{current.line_start}-{current.line_end}) "
                    f"and {nxt.finding_id} (L{nxt.line_start}-{nxt.line_end})"
                )
