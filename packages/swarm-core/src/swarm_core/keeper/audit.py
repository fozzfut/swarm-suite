"""CLAUDE.md audit logic.

Detects four classes of drift:
    1. SIZE        file too long (rule of thumb: a doc you can't re-read in
                   one sitting stops being read at all).
    2. ACCRETION   tactical bug-fix recipes that should live in docs/decisions/.
    3. STRUCTURE   missing required headings.
    4. POINTERS    missing references to docs/INDEX.md, docs/architecture/, etc.

Returns a `KeeperReport` with severity-tagged findings and concrete
"move this to <path>" suggestions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..models.severity import Severity

# Phrases that signal accreted bug-fix content.
#
# We intentionally require a colon / dash after Bug/Symptom/Cause/Fix to
# avoid catching rules-doc headings like "## Bug Hunting Rules". A real
# bug post-mortem heading looks like `## Bug: <description>` or
# `### Symptom: <observed behavior>`.
_ACCRETION_PATTERNS = [
    re.compile(r"^##+\s*(Bug|Symptom|Cause|Fix|Workaround|Post-mortem|Incident)\s*[:\-]", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\bFixed in (commit\s+)?[a-f0-9]{6,}\b", re.IGNORECASE),
    re.compile(r"\bWorkaround for (issue|bug|PR)\s*#?\d+\b", re.IGNORECASE),
    re.compile(r"\bRegression introduced by\b", re.IGNORECASE),
    re.compile(r"\bSee PR\s*#\d+\b", re.IGNORECASE),
]

_REQUIRED_HEADINGS = (
    "Mission",
    "Critical Rules",
    "Architecture Principles",
    "Module Boundaries",
    "RAG Update Rule",
)

_RECOMMENDED_POINTERS = (
    "docs/INDEX.md",
    "docs/architecture/",
    "docs/decisions/",
    "GUIDE.md",
)

SOFT_SIZE_LIMIT = 800
HARD_SIZE_LIMIT = 1200
# Reject CLAUDE.md files larger than this -- the keeper is a lint tool,
# not a viewer for arbitrary files. 1 MB covers any plausible rules
# document; anything larger is suspicious (or a typo for a different
# file passed by mistake). Caps memory usage when an MCP caller passes
# an arbitrary path.
MAX_FILE_BYTES = 1_048_576  # 1 MiB


@dataclass
class KeeperFinding:
    severity: Severity
    category: str   # "size" | "accretion" | "structure" | "pointers"
    line: int       # 0 if file-level
    title: str
    detail: str = ""
    suggested_destination: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "category": self.category,
            "line": self.line,
            "title": self.title,
            "detail": self.detail,
            "suggested_destination": self.suggested_destination,
        }


@dataclass
class KeeperReport:
    file: str
    findings: list[KeeperFinding] = field(default_factory=list)
    line_count: int = 0

    @property
    def has_blockers(self) -> bool:
        return any(f.severity in (Severity.CRITICAL, Severity.HIGH) for f in self.findings)

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line_count": self.line_count,
            "has_blockers": self.has_blockers,
            "findings": [f.to_dict() for f in self.findings],
        }


def audit_claude_md(path: Path | str) -> KeeperReport:
    """Run all keeper checks on `path` and return the report.

    `path` may not exist -- the report will record a single CRITICAL
    finding rather than raising.
    """
    p = Path(path)
    report = KeeperReport(file=str(p))

    if not p.is_file():
        report.findings.append(KeeperFinding(
            severity=Severity.CRITICAL,
            category="structure",
            line=0,
            title=f"CLAUDE.md not found at {p}",
            detail="Create CLAUDE.md at the repo root with Mission, Critical Rules, Architecture Principles sections.",
        ))
        return report

    # Bound file size before reading -- prevents OOM if an MCP caller
    # passes a large arbitrary path. 1 MiB is well above any plausible
    # CLAUDE.md.
    try:
        size = p.stat().st_size
    except OSError as exc:
        report.findings.append(KeeperFinding(
            severity=Severity.CRITICAL, category="structure", line=0,
            title=f"cannot stat {p}", detail=str(exc),
        ))
        return report
    if size > MAX_FILE_BYTES:
        report.findings.append(KeeperFinding(
            severity=Severity.CRITICAL, category="size", line=0,
            title=f"file rejected: {size} bytes exceeds {MAX_FILE_BYTES} byte cap",
            detail="Keeper audits rules docs; large files are out of scope. Pass a smaller CLAUDE.md or split.",
        ))
        return report

    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    report.line_count = len(lines)

    _check_size(report, len(lines))
    _check_accretion(report, text)
    _check_structure(report, text)
    _check_pointers(report, text)
    return report


def _check_size(report: KeeperReport, line_count: int) -> None:
    if line_count > HARD_SIZE_LIMIT:
        report.findings.append(KeeperFinding(
            severity=Severity.HIGH,
            category="size",
            line=0,
            title=f"CLAUDE.md exceeds hard limit ({line_count} > {HARD_SIZE_LIMIT} lines)",
            detail="Move detail-heavy sections to docs/architecture/ or docs/features/. CLAUDE.md is a rules doc, not an encyclopedia.",
        ))
    elif line_count > SOFT_SIZE_LIMIT:
        report.findings.append(KeeperFinding(
            severity=Severity.MEDIUM,
            category="size",
            line=0,
            title=f"CLAUDE.md approaching soft limit ({line_count} > {SOFT_SIZE_LIMIT} lines)",
            detail="Consider moving the longest sections to docs/architecture/. Re-readability decays past 800 lines.",
        ))


def _check_accretion(report: KeeperReport, text: str) -> None:
    for pattern in _ACCRETION_PATTERNS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            snippet = match.group(0)
            report.findings.append(KeeperFinding(
                severity=Severity.HIGH,
                category="accretion",
                line=line,
                title=f"Tactical bug-fix content in CLAUDE.md ({snippet!r})",
                detail="Bug post-mortems, fix recipes, and workaround narratives belong in docs/decisions/. CLAUDE.md should reference them, not contain them.",
                suggested_destination="docs/decisions/<date>-<slug>.md",
            ))


def _check_structure(report: KeeperReport, text: str) -> None:
    for heading in _REQUIRED_HEADINGS:
        # Match "## Mission" or "### Mission" (any depth)
        if not re.search(rf"^#+\s*{re.escape(heading)}\b", text, re.MULTILINE):
            report.findings.append(KeeperFinding(
                severity=Severity.MEDIUM,
                category="structure",
                line=0,
                title=f"Missing required heading: {heading}",
                detail=f"Every Swarm Suite CLAUDE.md must declare a `## {heading}` section.",
            ))


def _check_pointers(report: KeeperReport, text: str) -> None:
    missing = [p for p in _RECOMMENDED_POINTERS if p not in text]
    if missing:
        report.findings.append(KeeperFinding(
            severity=Severity.LOW,
            category="pointers",
            line=0,
            title=f"Missing pointers to: {', '.join(missing)}",
            detail="CLAUDE.md should point readers at the deeper docs trees so they don't try to find everything in this file.",
        ))
