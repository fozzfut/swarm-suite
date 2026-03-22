"""Data models for FixSwarm -- FixAction, FixPlan, FixResult."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FixActionType(str, Enum):
    """The kind of text transformation to apply."""

    REPLACE = "replace"
    INSERT = "insert"
    DELETE = "delete"


class Severity(str, Enum):
    """Mirror of ReviewSwarm severity levels, ordered high-to-low."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# Severity ordering: lower index == higher priority.
SEVERITY_ORDER: list[Severity] = [
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
]


def severity_at_least(sev: Severity, threshold: Severity) -> bool:
    """Return True if *sev* is at least as severe as *threshold*."""
    try:
        return SEVERITY_ORDER.index(sev) <= SEVERITY_ORDER.index(threshold)
    except ValueError:
        return False


@dataclass
class FixAction:
    """A single text-level fix to apply to a source file."""

    finding_id: str
    file: str
    line_start: int
    line_end: int
    action: FixActionType
    old_text: str
    new_text: str
    rationale: str

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "action": self.action.value,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, d: dict) -> FixAction:
        return cls(
            finding_id=d["finding_id"],
            file=d["file"],
            line_start=d["line_start"],
            line_end=d["line_end"],
            action=FixActionType(d["action"]),
            old_text=d.get("old_text", ""),
            new_text=d.get("new_text", ""),
            rationale=d.get("rationale", ""),
        )


@dataclass
class FixPlan:
    """An ordered collection of fix actions grouped by file."""

    actions: list[FixAction] = field(default_factory=list)

    def files(self) -> list[str]:
        """Return sorted list of unique files touched by this plan."""
        return sorted({a.file for a in self.actions})

    def actions_for_file(self, path: str) -> list[FixAction]:
        """Return actions for *path*, sorted by line_start descending.

        Descending order ensures earlier fixes don't shift line numbers
        for later fixes in the same file.
        """
        return sorted(
            [a for a in self.actions if a.file == path],
            key=lambda a: a.line_start,
            reverse=True,
        )

    def to_dict(self) -> dict:
        return {"actions": [a.to_dict() for a in self.actions]}

    @classmethod
    def from_dict(cls, d: dict) -> FixPlan:
        return cls(actions=[FixAction.from_dict(a) for a in d.get("actions", [])])


@dataclass
class FixResult:
    """Outcome of applying a single FixAction."""

    finding_id: str
    success: bool
    error: Optional[str] = None
    diff: str = ""

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "success": self.success,
            "error": self.error,
            "diff": self.diff,
        }
