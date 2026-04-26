"""Severity scale -- the same five buckets across every tool in the suite."""

from __future__ import annotations

from enum import Enum


class Severity(str, Enum):
    """Severity scale for findings, fix proposals, doc issues, etc.

    Ordered high-to-low. Use `SEVERITY_ORDER` for index-based comparison
    or `severity_at_least` for predicate use.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


SEVERITY_ORDER: list[Severity] = [
    Severity.CRITICAL,
    Severity.HIGH,
    Severity.MEDIUM,
    Severity.LOW,
    Severity.INFO,
]


def severity_at_least(sev: Severity, threshold: Severity) -> bool:
    """Return True if `sev` is at least as severe as `threshold`.

    Falls back to False on values outside the canonical scale.
    """
    try:
        return SEVERITY_ORDER.index(sev) <= SEVERITY_ORDER.index(threshold)
    except ValueError:
        return False
