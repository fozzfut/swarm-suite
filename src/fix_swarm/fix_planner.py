"""Generate a FixPlan from parsed findings by reading actual source files."""

from __future__ import annotations

from pathlib import Path

from .models import FixAction, FixActionType, FixPlan
from .report_parser import ParsedFinding


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

        source_path = (base / finding.file).resolve()
        if not source_path.resolve().is_relative_to(base.resolve()):
            continue  # skip files outside project
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

        if not new_text.strip():
            # Nothing concrete to replace with -- skip.
            continue

        if new_text.strip() == old_text.strip():
            # No-op replacement -- skip.
            continue

        # Determine action type (DELETE no longer possible here --
        # whitespace-only new_text is skipped above)
        if not old_text.strip():
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
    return _deduplicate_overlaps(plan)


def _deduplicate_overlaps(plan: FixPlan) -> FixPlan:
    """Deduplicate actions that overlap on the same file+line range.

    When multiple ReviewSwarm experts report the same bug on the same lines,
    keep the first (highest-priority) action and drop duplicates.
    """
    deduped: list[FixAction] = []

    for file_path in plan.files():
        file_actions = sorted(
            [a for a in plan.actions if a.file == file_path],
            key=lambda a: a.line_start,
        )
        if not file_actions:
            continue

        kept = file_actions[0]
        for nxt in file_actions[1:]:
            if kept.line_end >= nxt.line_start:
                # Overlap — skip the duplicate, keep the first
                continue
            deduped.append(kept)
            kept = nxt
        deduped.append(kept)

    return FixPlan(actions=deduped)
