"""Tests for fix_swarm.fix_planner."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from fix_swarm.fix_planner import build_plan
from fix_swarm.models import FixActionType, Severity
from fix_swarm.report_parser import ParsedFinding, parse_report


class TestBuildPlan:
    """FixPlan generation from findings."""

    def test_plan_from_report(
        self, sample_report_json: Path, tmp_source: Path,
    ) -> None:
        findings = parse_report(sample_report_json, threshold=Severity.INFO)
        plan = build_plan(findings, base_dir=tmp_source.parent)
        assert len(plan.actions) == 2
        assert set(plan.files()) == {"example.py"}

    def test_actions_are_replace(
        self, sample_report_json: Path, tmp_source: Path,
    ) -> None:
        findings = parse_report(sample_report_json, threshold=Severity.INFO)
        plan = build_plan(findings, base_dir=tmp_source.parent)
        for action in plan.actions:
            assert action.action == FixActionType.REPLACE

    def test_non_fix_suggestions_skipped(self, tmp_path: Path) -> None:
        src = tmp_path / "code.py"
        src.write_text("x = 1\n", encoding="utf-8")
        findings = [
            ParsedFinding(
                id="f-inv",
                file="code.py",
                line_start=1,
                line_end=1,
                severity=Severity.HIGH,
                category="bug",
                title="Investigate this",
                actual="something",
                expected="something else",
                suggestion_action="investigate",
                suggestion_detail="look into it",
            ),
        ]
        plan = build_plan(findings, base_dir=tmp_path)
        assert len(plan.actions) == 0

    def test_missing_file_skipped(self, tmp_path: Path) -> None:
        findings = [
            ParsedFinding(
                id="f-missing",
                file="nonexistent.py",
                line_start=1,
                line_end=1,
                severity=Severity.HIGH,
                category="bug",
                title="Missing file",
                actual="",
                expected="",
                suggestion_action="fix",
                suggestion_detail="new content\n",
            ),
        ]
        plan = build_plan(findings, base_dir=tmp_path)
        assert len(plan.actions) == 0

    def test_overlap_deduplication(self, tmp_path: Path) -> None:
        src = tmp_path / "overlap.py"
        src.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
        findings = [
            ParsedFinding(
                id="f-ov1",
                file="overlap.py",
                line_start=1,
                line_end=3,
                severity=Severity.HIGH,
                category="bug",
                title="Fix A",
                actual="",
                expected="",
                suggestion_action="fix",
                suggestion_detail="replaced A\n",
            ),
            ParsedFinding(
                id="f-ov2",
                file="overlap.py",
                line_start=2,
                line_end=4,
                severity=Severity.HIGH,
                category="bug",
                title="Fix B",
                actual="",
                expected="",
                suggestion_action="fix",
                suggestion_detail="replaced B\n",
            ),
        ]
        plan = build_plan(findings, base_dir=tmp_path)
        # Overlapping findings are deduplicated -- keep first, drop duplicate
        assert len(plan.actions) == 1
        assert plan.actions[0].finding_id == "f-ov1"

    def test_non_overlapping_same_file(self, tmp_path: Path) -> None:
        src = tmp_path / "multi.py"
        src.write_text("a\nb\nc\nd\ne\nf\n", encoding="utf-8")
        findings = [
            ParsedFinding(
                id="f-no1",
                file="multi.py",
                line_start=1,
                line_end=2,
                severity=Severity.HIGH,
                category="bug",
                title="Fix top",
                actual="",
                expected="",
                suggestion_action="fix",
                suggestion_detail="A\nB\n",
            ),
            ParsedFinding(
                id="f-no2",
                file="multi.py",
                line_start=5,
                line_end=6,
                severity=Severity.HIGH,
                category="bug",
                title="Fix bottom",
                actual="",
                expected="",
                suggestion_action="fix",
                suggestion_detail="E\nF\n",
            ),
        ]
        plan = build_plan(findings, base_dir=tmp_path)
        assert len(plan.actions) == 2

    def test_plan_serialization_roundtrip(
        self, sample_report_json: Path, tmp_source: Path,
    ) -> None:
        findings = parse_report(sample_report_json, threshold=Severity.INFO)
        plan = build_plan(findings, base_dir=tmp_source.parent)
        data = plan.to_dict()
        from fix_swarm.models import FixPlan
        plan2 = FixPlan.from_dict(data)
        assert len(plan2.actions) == len(plan.actions)
        for a, b in zip(plan.actions, plan2.actions):
            assert a.finding_id == b.finding_id
            assert a.file == b.file
