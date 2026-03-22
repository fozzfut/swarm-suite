"""Tests for fix_swarm.cli (Click commands)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from fix_swarm.cli import main


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


class TestPlanCommand:
    """Tests for `fix-swarm plan`."""

    def test_plan_shows_actions(
        self,
        runner: CliRunner,
        sample_report_json: Path,
        tmp_source: Path,
    ) -> None:
        result = runner.invoke(main, [
            "plan", str(sample_report_json),
            "--base-dir", str(tmp_source.parent),
        ])
        assert result.exit_code == 0
        assert "action(s)" in result.output

    def test_plan_dry_run(
        self,
        runner: CliRunner,
        sample_report_json: Path,
        tmp_source: Path,
    ) -> None:
        result = runner.invoke(main, [
            "plan", str(sample_report_json),
            "--base-dir", str(tmp_source.parent),
            "--dry-run",
        ])
        assert result.exit_code == 0
        assert "dry-run" in result.output

    def test_plan_no_findings_above_threshold(
        self,
        runner: CliRunner,
        sample_report_json: Path,
        tmp_source: Path,
    ) -> None:
        result = runner.invoke(main, [
            "plan", str(sample_report_json),
            "--threshold", "critical",
            "--base-dir", str(tmp_source.parent),
        ])
        assert result.exit_code == 0
        assert "No findings" in result.output


class TestApplyCommand:
    """Tests for `fix-swarm apply`."""

    def test_apply_modifies_file(
        self,
        runner: CliRunner,
        sample_report_json: Path,
        tmp_source: Path,
    ) -> None:
        result = runner.invoke(main, [
            "apply", str(sample_report_json),
            "--base-dir", str(tmp_source.parent),
        ])
        assert result.exit_code == 0
        assert "succeeded" in result.output

        content = tmp_source.read_text(encoding="utf-8")
        assert "a + b" in content

    def test_apply_with_backup(
        self,
        runner: CliRunner,
        sample_report_json: Path,
        tmp_source: Path,
    ) -> None:
        result = runner.invoke(main, [
            "apply", str(sample_report_json),
            "--base-dir", str(tmp_source.parent),
            "--backup",
        ])
        assert result.exit_code == 0
        backup = tmp_source.parent / "example.py.bak"
        assert backup.exists()
        # Backup should have original content
        assert "a - b" in backup.read_text(encoding="utf-8")

    def test_apply_no_actionable(
        self,
        runner: CliRunner,
        low_severity_report_json: Path,
    ) -> None:
        result = runner.invoke(main, [
            "apply", str(low_severity_report_json),
            "--threshold", "high",
        ])
        assert result.exit_code == 0
        assert "No findings" in result.output


class TestVerifyCommand:
    """Tests for `fix-swarm verify`."""

    def test_verify_after_apply(
        self,
        runner: CliRunner,
        sample_report_json: Path,
        tmp_source: Path,
    ) -> None:
        # First apply
        runner.invoke(main, [
            "apply", str(sample_report_json),
            "--base-dir", str(tmp_source.parent),
        ])
        # Then verify
        result = runner.invoke(main, [
            "verify", str(sample_report_json),
            "--base-dir", str(tmp_source.parent),
        ])
        assert result.exit_code == 0
        assert "passed" in result.output

    def test_verify_before_apply_fails(
        self,
        runner: CliRunner,
        sample_report_json: Path,
        tmp_source: Path,
    ) -> None:
        result = runner.invoke(main, [
            "verify", str(sample_report_json),
            "--base-dir", str(tmp_source.parent),
        ])
        # Should report failures since fixes haven't been applied yet
        assert result.exit_code == 1
        assert "FAIL" in result.output


class TestVersionFlag:
    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.2" in result.output
