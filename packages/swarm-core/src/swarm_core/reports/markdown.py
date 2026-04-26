"""Markdown rendering helpers -- the only place we build tables and badges.

Tools that build their own report markdown should call these helpers
instead of inlining f-string `f"| {x} |"` -- otherwise we end up with
five different table styles across reports.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from ..models.severity import Severity

_SEVERITY_BADGES = {
    Severity.CRITICAL: "[CRITICAL]",
    Severity.HIGH: "[HIGH]",
    Severity.MEDIUM: "[MEDIUM]",
    Severity.LOW: "[LOW]",
    Severity.INFO: "[INFO]",
}


def heading(text: str, level: int = 1) -> str:
    if not 1 <= level <= 6:
        raise ValueError(f"heading level must be 1..6, got {level}")
    return f"{'#' * level} {text}\n"


def table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    head = "| " + " | ".join(_escape_cell(h) for h in headers) + " |"
    sep = "|" + "|".join("---" for _ in headers) + "|"
    body = "\n".join(
        "| " + " | ".join(_escape_cell(str(c)) for c in row) + " |"
        for row in rows
    )
    return f"{head}\n{sep}\n{body}\n" if body else f"{head}\n{sep}\n"


def code_block(code: str, lang: str = "") -> str:
    return f"```{lang}\n{code}\n```\n"


def severity_badge(sev: Severity) -> str:
    return _SEVERITY_BADGES.get(sev, f"[{sev.value.upper()}]")


def finding_line(finding: dict) -> str:
    """Render one finding as a one-line bullet for a summary table."""
    sev_value = finding.get("severity", "info")
    try:
        sev = Severity(sev_value)
    except ValueError:
        sev = Severity.INFO
    file = finding.get("file", "?")
    line = finding.get("line_start", "?")
    title = finding.get("title", "(untitled)")
    return f"- {severity_badge(sev)} `{file}:{line}` -- {title}"


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
