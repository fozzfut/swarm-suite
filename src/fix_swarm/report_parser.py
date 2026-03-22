"""Parse ReviewSwarm report files (JSON and Markdown) into structured findings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Severity, severity_at_least


@dataclass
class ParsedFinding:
    """A finding extracted from a ReviewSwarm report, ready for fix planning."""

    id: str
    file: str
    line_start: int
    line_end: int
    severity: Severity
    category: str
    title: str
    actual: str
    expected: str
    suggestion_action: str
    suggestion_detail: str
    snippet: str = ""
    confidence: float = 0.5
    status: str = "open"
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "file": self.file,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "severity": self.severity.value,
            "category": self.category,
            "title": self.title,
            "actual": self.actual,
            "expected": self.expected,
            "suggestion_action": self.suggestion_action,
            "suggestion_detail": self.suggestion_detail,
            "snippet": self.snippet,
            "confidence": self.confidence,
            "status": self.status,
            "tags": list(self.tags),
        }


def parse_report(
    report_path: str | Path,
    threshold: Severity = Severity.MEDIUM,
) -> list[ParsedFinding]:
    """Parse a ReviewSwarm report file and return findings at or above *threshold*.

    Supports both JSON (``report.json``) and Markdown (``report.md``) formats.
    """
    path = Path(report_path)
    text = path.read_text(encoding="utf-8")

    if path.suffix == ".json" or _looks_like_json(text):
        findings = _parse_json(text)
    else:
        findings = _parse_markdown(text)

    return [
        f for f in findings
        if severity_at_least(f.severity, threshold)
    ]


def parse_report_text(
    text: str,
    fmt: str = "json",
    threshold: Severity = Severity.MEDIUM,
) -> list[ParsedFinding]:
    """Parse report content from a string (useful for testing)."""
    if fmt == "json":
        findings = _parse_json(text)
    else:
        findings = _parse_markdown(text)
    return [
        f for f in findings
        if severity_at_least(f.severity, threshold)
    ]


# ── JSON parser ────────────────────────────────────────────────────────


def _looks_like_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def _parse_json(text: str) -> list[ParsedFinding]:
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in report: {exc}") from exc

    # The JSON report has {"summary": {...}, "findings": [...]}
    if isinstance(data, dict) and "findings" in data:
        raw_findings = data["findings"]
    elif isinstance(data, list):
        raw_findings = data
    else:
        return []

    results: list[ParsedFinding] = []
    for d in raw_findings:
        try:
            results.append(_finding_from_dict(d))
        except (KeyError, ValueError):
            continue  # skip malformed findings
    return results


def _finding_from_dict(d: dict) -> ParsedFinding:
    return ParsedFinding(
        id=d["id"],
        file=d["file"],
        line_start=int(d["line_start"]),
        line_end=int(d["line_end"]),
        severity=Severity(d["severity"]),
        category=d.get("category", "bug"),
        title=d.get("title", ""),
        actual=d.get("actual", ""),
        expected=d.get("expected", ""),
        suggestion_action=d.get("suggestion_action", "investigate"),
        suggestion_detail=d.get("suggestion_detail", ""),
        snippet=d.get("snippet", ""),
        confidence=float(d.get("confidence", 0.5)),
        status=d.get("status", "open"),
        tags=d.get("tags", []),
    )


# ── Markdown parser ───────────────────────────────────────────────────

_SEV_RE = re.compile(r"\*\*Severity:\*\*\s*(\w+)", re.IGNORECASE)
_CAT_RE = re.compile(r"\*\*Category:\*\*\s*(\w+)", re.IGNORECASE)
_FILE_RE = re.compile(r"\*\*File:\*\*\s*`(.+?):(\d+)-(\d+)`", re.IGNORECASE)
_ACTUAL_RE = re.compile(r"\*\*Actual:\*\*\s*(.+)", re.IGNORECASE)
_EXPECTED_RE = re.compile(r"\*\*Expected:\*\*\s*(.+)", re.IGNORECASE)
_SUGGESTION_RE = re.compile(
    r"\*\*Suggestion:\*\*\s*\[(\w+)\]\s*(.*)", re.IGNORECASE,
)
_CONFIDENCE_RE = re.compile(r"\*\*Confidence:\*\*\s*([\d.]+%?)", re.IGNORECASE)


def _parse_markdown(text: str) -> list[ParsedFinding]:
    """Best-effort extraction of findings from ReviewSwarm markdown reports."""
    results: list[ParsedFinding] = []
    # Split by "### " headings to isolate individual finding blocks
    blocks = re.split(r"(?=^### )", text, flags=re.MULTILINE)
    finding_counter = 0

    for block in blocks:
        file_m = _FILE_RE.search(block)
        if not file_m:
            continue  # not a finding block

        sev_m = _SEV_RE.search(block)
        severity_str = sev_m.group(1).lower() if sev_m else "medium"
        try:
            severity = Severity(severity_str)
        except ValueError:
            severity = Severity.MEDIUM

        cat_m = _CAT_RE.search(block)
        category = cat_m.group(1).lower() if cat_m else "bug"

        # Extract title from "### Some Title [status]"
        title_m = re.match(r"###\s+(.+?)(?:\s*\[.*\])?\s*$", block, re.MULTILINE)
        title = title_m.group(1).strip() if title_m else ""

        actual_m = _ACTUAL_RE.search(block)
        actual = actual_m.group(1).strip() if actual_m else ""

        expected_m = _EXPECTED_RE.search(block)
        expected = expected_m.group(1).strip() if expected_m else ""

        sug_m = _SUGGESTION_RE.search(block)
        suggestion_action = sug_m.group(1).lower() if sug_m else "investigate"
        suggestion_detail = sug_m.group(2).strip() if sug_m else ""

        conf_m = _CONFIDENCE_RE.search(block)
        if conf_m:
            raw = conf_m.group(1)
            confidence = float(raw.rstrip("%")) / 100 if "%" in raw else float(raw)
        else:
            confidence = 0.5

        finding_counter += 1
        results.append(ParsedFinding(
            id=f"md-{finding_counter}",
            file=file_m.group(1),
            line_start=int(file_m.group(2)),
            line_end=int(file_m.group(3)),
            severity=severity,
            category=category,
            title=title,
            actual=actual,
            expected=expected,
            suggestion_action=suggestion_action,
            suggestion_detail=suggestion_detail,
            confidence=confidence,
        ))

    return results
