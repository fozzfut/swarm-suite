"""Shared fixtures for FixSwarm tests."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_source(tmp_path: Path) -> Path:
    """Create a small Python source file for fix testing."""
    src = tmp_path / "example.py"
    src.write_text(textwrap.dedent("""\
        import os
        import sys

        def greet(name):
            print("hello " + name)

        def add(a, b):
            return a - b

        if __name__ == "__main__":
            greet("world")
    """), encoding="utf-8")
    return src


@pytest.fixture()
def sample_report_json(tmp_path: Path, tmp_source: Path) -> Path:
    """Create a sample ReviewSwarm JSON report with two findings."""
    report = {
        "summary": {
            "total": 2,
            "by_severity": {"high": 1, "medium": 1},
            "by_status": {"open": 2},
        },
        "findings": [
            {
                "id": "f-abc123",
                "session_id": "s-test",
                "expert_role": "logic-auditor",
                "agent_id": "agent-1",
                "file": "example.py",
                "line_start": 8,
                "line_end": 8,
                "snippet": "return a - b",
                "severity": "high",
                "category": "bug",
                "title": "Wrong operator in add function",
                "actual": "Function subtracts instead of adding",
                "expected": "Function should add a + b",
                "source_ref": "",
                "suggestion_action": "fix",
                "suggestion_detail": "    return a + b\n",
                "confidence": 0.95,
                "tags": ["arithmetic"],
                "related_findings": [],
                "status": "open",
                "reactions": [],
                "comments": [],
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "id": "f-def456",
                "session_id": "s-test",
                "expert_role": "style-checker",
                "agent_id": "agent-2",
                "file": "example.py",
                "line_start": 5,
                "line_end": 5,
                "snippet": 'print("hello " + name)',
                "severity": "medium",
                "category": "style",
                "title": "Use f-string instead of concatenation",
                "actual": "String concatenation used",
                "expected": "f-string preferred",
                "source_ref": "",
                "suggestion_action": "fix",
                "suggestion_detail": '    print(f"hello {name}")\n',
                "confidence": 0.8,
                "tags": ["style"],
                "related_findings": [],
                "status": "open",
                "reactions": [],
                "comments": [],
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
        ],
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


@pytest.fixture()
def sample_report_md(tmp_path: Path) -> Path:
    """Create a sample ReviewSwarm Markdown report."""
    md = textwrap.dedent("""\
        # Review Report

        ## Executive Summary

        **2 findings** total
        By severity: 1 high, 1 medium

        ## Critical & High Findings

        ### Wrong operator in add function

        - **Severity:** high | **Category:** bug
        - **File:** `example.py:8-8`
        - **Actual:** Function subtracts instead of adding
        - **Expected:** Function should add a + b
        - **Source:** ``
        - **Suggestion:** [fix] return a + b
        - **Confidence:** 95%

        ## Per-File Breakdown

        ### example.py (2 findings)

        - **[HIGH]** Wrong operator in add function (L8-8, open)
        - **[MEDIUM]** Use f-string instead of concatenation (L5-5, open)
    """)
    report_path = tmp_path / "report.md"
    report_path.write_text(md, encoding="utf-8")
    return report_path


@pytest.fixture()
def low_severity_report_json(tmp_path: Path) -> Path:
    """Report where findings are below the default 'medium' threshold."""
    report = {
        "summary": {"total": 1, "by_severity": {"info": 1}, "by_status": {"open": 1}},
        "findings": [
            {
                "id": "f-low001",
                "session_id": "s-test",
                "expert_role": "style-checker",
                "agent_id": "agent-3",
                "file": "example.py",
                "line_start": 1,
                "line_end": 1,
                "severity": "info",
                "category": "style",
                "title": "Consider adding module docstring",
                "actual": "No module docstring",
                "expected": "Module docstring present",
                "suggestion_action": "fix",
                "suggestion_detail": '"""Example module."""\n',
                "confidence": 0.6,
                "status": "open",
                "reactions": [],
                "comments": [],
                "tags": [],
                "related_findings": [],
                "created_at": "",
                "updated_at": "",
            },
        ],
    }
    path = tmp_path / "low_report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
