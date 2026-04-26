"""MCP tool wrappers around `audit_claude_md`.

These are registered on `swarm-kb`'s MCPApp (so the keeper is reachable
as `kb_check_claude_md` to AI clients) but the implementation lives
here so the keeper logic stays in `swarm_core` where it belongs.

The wrappers are intentionally tiny -- the audit object does the work.
"""

from __future__ import annotations

from pathlib import Path

from .audit import audit_claude_md, KeeperReport


def kb_check_claude_md(path: str = "CLAUDE.md") -> dict:
    """Audit a CLAUDE.md file.

    Returns the keeper report as a dict suitable for JSON serialization.

    Args:
        path: path to the CLAUDE.md to audit. Relative paths resolve
            against the current working directory.

    Returns:
        Dict with keys: file, line_count, has_blockers, findings (list).

    Use as a `kb_advance_pipeline` gate: if `has_blockers` is True the
    pipeline should refuse to advance until the doc is brought back into
    rules-only shape.
    """
    report = audit_claude_md(Path(path))
    return report.to_dict()


def kb_check_claude_md_summary(path: str = "CLAUDE.md") -> str:
    """Human-readable one-line summary of the keeper report."""
    report = audit_claude_md(Path(path))
    if not report.findings:
        return f"OK ({report.line_count} lines, no findings)"
    sev_counts = _count_by_severity(report)
    counts = ", ".join(f"{n} {s}" for s, n in sev_counts.items() if n)
    return f"{report.line_count} lines, findings: {counts}"


def _count_by_severity(report: KeeperReport) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in report.findings:
        out[f.severity.value] = out.get(f.severity.value, 0) + 1
    return out
