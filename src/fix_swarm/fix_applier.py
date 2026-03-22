"""Apply a FixPlan to actual source files, with backup and dry-run support."""

from __future__ import annotations

import difflib
import os
import shutil
import tempfile
from pathlib import Path

from .models import FixAction, FixActionType, FixPlan, FixResult


def apply_plan(
    plan: FixPlan,
    base_dir: str | Path = ".",
    dry_run: bool = False,
    backup: bool = False,
) -> list[FixResult]:
    """Apply every action in *plan* and return a FixResult per action.

    Args:
        plan: The fix plan to apply.
        base_dir: Root directory that file paths are relative to.
        dry_run: If True, compute diffs but do not write files.
        backup: If True, copy each file to ``<file>.bak`` before modifying.

    Returns:
        A list of FixResult, one per FixAction in the plan.
    """
    base = Path(base_dir)
    results: list[FixResult] = []

    for file_path in plan.files():
        source = base / file_path
        if not source.is_file():
            for action in plan.actions_for_file(file_path):
                results.append(FixResult(
                    finding_id=action.finding_id,
                    success=False,
                    error=f"File not found: {source}",
                ))
            continue

        try:
            original_text = source.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            for action in plan.actions_for_file(file_path):
                results.append(FixResult(
                    finding_id=action.finding_id,
                    success=False,
                    error=str(exc),
                ))
            continue
        lines = original_text.splitlines(keepends=True)

        if backup and not dry_run:
            shutil.copy2(source, str(source) + ".bak")

        # Actions are returned in descending line order, so applying
        # from the bottom up keeps earlier line numbers valid.
        actions = plan.actions_for_file(file_path)
        original_lines = list(lines)  # snapshot for rollback
        file_failed = False
        for action in actions:
            result = _apply_action(action, lines)
            if not result.success:
                # Rollback all changes for this file
                lines = original_lines
                results.append(result)
                # Mark remaining actions as failed too
                idx = actions.index(action)
                for remaining in actions[idx + 1:]:
                    results.append(FixResult(
                        finding_id=remaining.finding_id,
                        success=False,
                        error="Skipped due to earlier failure in same file",
                    ))
                file_failed = True
                break
            results.append(result)
        if file_failed:
            continue

        new_text = "".join(lines)
        # Compute unified diff for the whole file
        file_diff = "".join(difflib.unified_diff(
            original_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        ))
        # Attach diff to the last result for this file
        for r in reversed(results):
            if r.success and r.finding_id in {a.finding_id for a in actions}:
                r.diff = file_diff
                break

        if not dry_run:
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=str(source.parent), suffix=".tmp",
            )
            try:
                fh = os.fdopen(tmp_fd, "w", encoding="utf-8")
            except Exception:
                os.close(tmp_fd)
                os.unlink(tmp_path)
                raise
            try:
                with fh:
                    fh.write(new_text)
                os.replace(tmp_path, str(source))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

    return results


def _apply_action(action: FixAction, lines: list[str]) -> FixResult:
    """Mutate *lines* in-place for a single FixAction. Return a FixResult."""
    start = action.line_start - 1  # convert to 0-index
    end = action.line_end          # exclusive upper bound for slice

    if start < 0 or start > len(lines):
        return FixResult(
            finding_id=action.finding_id,
            success=False,
            error=f"line_start {action.line_start} out of range (file has {len(lines)} lines)",
        )
    if end > len(lines):
        end = len(lines)

    try:
        if action.action == FixActionType.DELETE:
            lines[start:end] = []
        elif action.action == FixActionType.INSERT:
            new_lines = _ensure_newlines(action.new_text)
            lines[start:start] = new_lines
        elif action.action == FixActionType.REPLACE:
            new_lines = _ensure_newlines(action.new_text)
            lines[start:end] = new_lines
        else:
            return FixResult(
                finding_id=action.finding_id,
                success=False,
                error=f"Unknown action type: {action.action}",
            )
    except Exception as exc:
        return FixResult(
            finding_id=action.finding_id,
            success=False,
            error=str(exc),
        )

    return FixResult(finding_id=action.finding_id, success=True)


def _ensure_newlines(text: str) -> list[str]:
    """Split text into lines, each ending with a newline."""
    if not text:
        return []
    result = text.splitlines(keepends=True)
    # Ensure last line ends with newline
    if result and not result[-1].endswith("\n"):
        result[-1] += "\n"
    return result


def verify_fixes(
    plan: FixPlan,
    base_dir: str | Path = ".",
) -> list[FixResult]:
    """Check whether the fixes in *plan* have been applied.

    For each REPLACE/INSERT action, verify that ``new_text`` is present
    in the file at approximately the right location. For DELETE actions,
    verify that ``old_text`` is absent.
    """
    base = Path(base_dir)
    results: list[FixResult] = []

    for action in plan.actions:
        source = base / action.file
        if not source.is_file():
            results.append(FixResult(
                finding_id=action.finding_id,
                success=False,
                error=f"File not found: {source}",
            ))
            continue

        content = source.read_text(encoding="utf-8")
        lines = content.splitlines()
        start = max(0, action.line_start - 1 - 5)
        end = min(len(lines), action.line_end + 5)
        window = "\n".join(lines[start:end])

        if action.action == FixActionType.DELETE:
            # old_text should be gone from the window
            if action.old_text.strip() and action.old_text.strip() in window:
                results.append(FixResult(
                    finding_id=action.finding_id,
                    success=False,
                    error="Deleted text still present in file",
                ))
            else:
                results.append(FixResult(
                    finding_id=action.finding_id, success=True,
                ))
        else:
            # new_text should be present in the window
            check_text = action.new_text.strip()
            if check_text and check_text in window:
                results.append(FixResult(
                    finding_id=action.finding_id, success=True,
                ))
            else:
                results.append(FixResult(
                    finding_id=action.finding_id,
                    success=False,
                    error="Expected text not found in file after fix",
                ))

    return results
