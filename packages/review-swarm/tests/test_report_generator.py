# tests/test_report_generator.py
from pathlib import Path

import pytest

from review_swarm.report_generator import ReportGenerator
from review_swarm.finding_store import FindingStore
from review_swarm.models import Finding, Severity, Category, Action, Status


def _make_finding(store, **overrides):
    defaults = dict(
        id=Finding.generate_id(),
        session_id="sess-001",
        expert_role="threading-safety",
        agent_id="agent-001",
        file="src/main.py",
        line_start=10, line_end=15,
        severity=Severity.HIGH,
        category=Category.BUG,
        title="Test finding",
        actual="does X", expected="should Y",
        source_ref="src/main.py:10",
        suggestion_action=Action.FIX,
        suggestion_detail="fix it",
        confidence=0.9,
        tags=[], related_findings=[],
    )
    defaults.update(overrides)
    f = Finding(**defaults)
    store.post(f)
    return f


class TestReportGenerator:
    def test_empty_report(self, tmp_path):
        jsonl = tmp_path / "findings.jsonl"
        jsonl.write_text("")
        store = FindingStore(jsonl)
        gen = ReportGenerator(store)

        report = gen.generate("sess-001")
        assert "# Review Report" in report
        assert "0 findings" in report.lower() or "no findings" in report.lower()

    def test_report_has_sections(self, tmp_path):
        jsonl = tmp_path / "findings.jsonl"
        jsonl.write_text("")
        store = FindingStore(jsonl)
        _make_finding(store, severity=Severity.CRITICAL, title="Critical bug")
        _make_finding(store, severity=Severity.HIGH, title="High bug")
        _make_finding(store, severity=Severity.LOW, title="Style issue")

        gen = ReportGenerator(store)
        report = gen.generate("sess-001")

        assert "## Executive Summary" in report
        assert "## Critical & High" in report
        assert "Critical bug" in report
        assert "High bug" in report

    def test_report_shows_disputed(self, tmp_path):
        jsonl = tmp_path / "findings.jsonl"
        jsonl.write_text("")
        store = FindingStore(jsonl)
        f = _make_finding(store, title="Disputed finding")
        store.update_status(f.id, Status.DISPUTED)

        gen = ReportGenerator(store)
        report = gen.generate("sess-001")

        assert "## Disputed" in report
        assert "Disputed finding" in report

    def test_report_per_file(self, tmp_path):
        jsonl = tmp_path / "findings.jsonl"
        jsonl.write_text("")
        store = FindingStore(jsonl)
        _make_finding(store, file="src/a.py", title="Bug in A")
        _make_finding(store, file="src/b.py", title="Bug in B")

        gen = ReportGenerator(store)
        report = gen.generate("sess-001")

        assert "src/a.py" in report
        assert "src/b.py" in report

    def test_json_format(self, tmp_path):
        jsonl = tmp_path / "findings.jsonl"
        jsonl.write_text("")
        store = FindingStore(jsonl)
        _make_finding(store)

        gen = ReportGenerator(store)
        import json
        result = gen.generate("sess-001", fmt="json")
        data = json.loads(result)
        assert "findings" in data
        assert "summary" in data

    def test_json_format_has_by_status(self, tmp_path):
        jsonl = tmp_path / "findings.jsonl"
        jsonl.write_text("")
        store = FindingStore(jsonl)
        f = _make_finding(store, title="Status test")
        store.update_status(f.id, Status.CONFIRMED)

        gen = ReportGenerator(store)
        import json
        result = gen.generate("sess-001", fmt="json")
        data = json.loads(result)
        assert "by_status" in data["summary"]
        assert data["summary"]["by_status"]["confirmed"] == 1
