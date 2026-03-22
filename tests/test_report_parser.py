"""Tests for fix_swarm.report_parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fix_swarm.models import Severity
from fix_swarm.report_parser import parse_report, parse_report_text


class TestParseJsonReport:
    """JSON report parsing."""

    def test_basic_parse(self, sample_report_json: Path) -> None:
        findings = parse_report(sample_report_json, threshold=Severity.INFO)
        assert len(findings) == 2

    def test_severity_threshold_filters(self, sample_report_json: Path) -> None:
        findings = parse_report(sample_report_json, threshold=Severity.HIGH)
        assert len(findings) == 1
        assert findings[0].id == "f-abc123"
        assert findings[0].severity == Severity.HIGH

    def test_default_threshold_is_medium(self, sample_report_json: Path) -> None:
        findings = parse_report(sample_report_json)
        # high and medium both pass the default medium threshold
        assert len(findings) == 2

    def test_critical_threshold_excludes_all(self, sample_report_json: Path) -> None:
        findings = parse_report(sample_report_json, threshold=Severity.CRITICAL)
        assert len(findings) == 0

    def test_finding_fields(self, sample_report_json: Path) -> None:
        findings = parse_report(sample_report_json, threshold=Severity.HIGH)
        f = findings[0]
        assert f.file == "example.py"
        assert f.line_start == 8
        assert f.line_end == 8
        assert f.category == "bug"
        assert f.suggestion_action == "fix"
        assert f.confidence == 0.95

    def test_low_severity_filtered_out(self, low_severity_report_json: Path) -> None:
        findings = parse_report(low_severity_report_json, threshold=Severity.MEDIUM)
        assert len(findings) == 0

    def test_low_severity_included_with_info_threshold(
        self, low_severity_report_json: Path,
    ) -> None:
        findings = parse_report(low_severity_report_json, threshold=Severity.INFO)
        assert len(findings) == 1

    def test_bare_list_format(self, tmp_path: Path) -> None:
        """Handle JSON files that are just a list of findings."""
        data = [
            {
                "id": "f-bare01",
                "file": "x.py",
                "line_start": 1,
                "line_end": 2,
                "severity": "high",
                "category": "bug",
                "title": "test",
                "actual": "",
                "expected": "",
                "suggestion_action": "fix",
                "suggestion_detail": "fixed\n",
                "status": "open",
            },
        ]
        p = tmp_path / "bare.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        findings = parse_report(p, threshold=Severity.INFO)
        assert len(findings) == 1
        assert findings[0].id == "f-bare01"


class TestParseMarkdownReport:
    """Markdown report parsing."""

    def test_basic_md_parse(self, sample_report_md: Path) -> None:
        findings = parse_report(sample_report_md, threshold=Severity.INFO)
        assert len(findings) >= 1  # at least the detailed finding block

    def test_md_finding_fields(self, sample_report_md: Path) -> None:
        findings = parse_report(sample_report_md, threshold=Severity.INFO)
        f = findings[0]
        assert f.file == "example.py"
        assert f.line_start == 8
        assert f.line_end == 8
        assert f.severity == Severity.HIGH

    def test_md_threshold_filters(self, sample_report_md: Path) -> None:
        findings = parse_report(sample_report_md, threshold=Severity.CRITICAL)
        assert len(findings) == 0


class TestParseReportText:
    """String-based parsing helper."""

    def test_json_text(self) -> None:
        text = json.dumps({
            "summary": {"total": 1},
            "findings": [{
                "id": "f-t1",
                "file": "a.py",
                "line_start": 1,
                "line_end": 1,
                "severity": "medium",
                "category": "bug",
                "suggestion_action": "fix",
                "suggestion_detail": "x\n",
                "status": "open",
            }],
        })
        findings = parse_report_text(text, fmt="json", threshold=Severity.INFO)
        assert len(findings) == 1

    def test_malformed_findings_skipped(self) -> None:
        text = json.dumps({
            "summary": {},
            "findings": [
                {"id": "f-good", "file": "a.py", "line_start": 1, "line_end": 1,
                 "severity": "high", "category": "bug", "suggestion_action": "fix",
                 "suggestion_detail": "ok\n", "status": "open"},
                {"broken": True},  # missing required keys
            ],
        })
        findings = parse_report_text(text, fmt="json", threshold=Severity.INFO)
        assert len(findings) == 1
