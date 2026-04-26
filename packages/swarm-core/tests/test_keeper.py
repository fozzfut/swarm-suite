"""Tests for the CLAUDE.md keeper."""

from pathlib import Path

from swarm_core.keeper import audit_claude_md
from swarm_core.models import Severity


def test_missing_file_is_critical(tmp_path: Path):
    report = audit_claude_md(tmp_path / "CLAUDE.md")
    assert report.has_blockers
    assert any(f.severity == Severity.CRITICAL for f in report.findings)


def test_well_formed_doc_passes(tmp_path: Path):
    md = tmp_path / "CLAUDE.md"
    md.write_text(
        "# Project\n\n"
        "## Mission\n\nWhat we do.\n\n"
        "## Critical Rules\n\nRule 1.\n\n"
        "## Architecture Principles\n\nSOLID.\n\n"
        "## Module Boundaries\n\nLayer rules.\n\n"
        "## RAG Update Rule\n\nUpdate docs/INDEX.md and docs/architecture/ and docs/decisions/. See GUIDE.md.\n",
        encoding="utf-8",
    )
    report = audit_claude_md(md)
    assert not report.has_blockers


def test_accretion_pattern_detected(tmp_path: Path):
    md = tmp_path / "CLAUDE.md"
    md.write_text(
        "# x\n\n"
        "## Mission\n\n"
        "## Critical Rules\n"
        "## Architecture Principles\n"
        "## Module Boundaries\n"
        "## RAG Update Rule\n\n"
        "Workaround for issue #42 below.\n",
        encoding="utf-8",
    )
    report = audit_claude_md(md)
    accretion = [f for f in report.findings if f.category == "accretion"]
    assert accretion
    assert accretion[0].severity == Severity.HIGH


def test_rules_doc_headings_are_not_accretion(tmp_path: Path):
    md = tmp_path / "CLAUDE.md"
    md.write_text(
        "# x\n\n"
        "## Mission\n\n"
        "## Critical Rules\n\n"
        "### Bug Hunting Rules\n\n"
        "Some rules.\n\n"
        "## Architecture Principles\n"
        "## Module Boundaries\n"
        "## RAG Update Rule\n",
        encoding="utf-8",
    )
    report = audit_claude_md(md)
    accretion = [f for f in report.findings if f.category == "accretion"]
    assert not accretion, accretion


def test_real_bug_heading_with_colon_is_accretion(tmp_path: Path):
    md = tmp_path / "CLAUDE.md"
    md.write_text(
        "# x\n\n"
        "## Mission\n## Critical Rules\n## Architecture Principles\n"
        "## Module Boundaries\n## RAG Update Rule\n\n"
        "## Bug: NullPointerException in CamelToSnake\n\n"
        "Detail.\n",
        encoding="utf-8",
    )
    report = audit_claude_md(md)
    accretion = [f for f in report.findings if f.category == "accretion"]
    assert accretion


def test_size_warning(tmp_path: Path):
    md = tmp_path / "CLAUDE.md"
    body = (
        "# x\n\n## Mission\n## Critical Rules\n## Architecture Principles\n"
        "## Module Boundaries\n## RAG Update Rule\n"
        + "\n".join(["filler"] * 1000)
    )
    md.write_text(body, encoding="utf-8")
    report = audit_claude_md(md)
    assert any(f.category == "size" for f in report.findings)
