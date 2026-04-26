"""Tests for arch_swarm.cli."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from arch_swarm.cli import main


class TestAnalyzeCommand:
    def test_analyze_runs(self, tmp_project: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["analyze", str(tmp_project), "--scope", "src/myapp"])
        assert result.exit_code == 0
        assert "Modules" in result.output

    def test_analyze_no_scope(self, tmp_project: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["analyze", str(tmp_project)])
        assert result.exit_code == 0


class TestDebateCommand:
    def test_debate_runs(self, tmp_project: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["debate", str(tmp_project), "--topic", "Split core.py?"],
        )
        assert result.exit_code == 0
        assert "Debate:" in result.output or "Proposal" in result.output

    def test_debate_saves_session(self, tmp_project: Path, tmp_path: Path, monkeypatch: object) -> None:
        import arch_swarm.cli as cli_mod

        session_dir = tmp_path / "sessions"
        monkeypatch.setattr(cli_mod, "_SESSION_DIR", session_dir)  # type: ignore[attr-defined]

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["debate", str(tmp_project), "--topic", "Test topic"],
        )
        assert result.exit_code == 0
        md_files = list(session_dir.glob("*.md"))
        assert len(md_files) == 1
        json_files = list(session_dir.glob("*.json"))
        assert len(json_files) == 1


class TestReportCommand:
    def test_report_missing_session(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["report", "nonexistent"])
        assert result.exit_code == 1

    def test_report_existing_session(self, tmp_path: Path, monkeypatch: object) -> None:
        import arch_swarm.cli as cli_mod

        session_dir = tmp_path / "sessions"
        session_dir.mkdir()
        monkeypatch.setattr(cli_mod, "_SESSION_DIR", session_dir)  # type: ignore[attr-defined]

        (session_dir / "abc123.md").write_text("# Debate transcript\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(main, ["report", "abc123"])
        assert result.exit_code == 0
        assert "Debate transcript" in result.output


class TestPromptCommand:
    """`arch-swarm prompt <expert>` should compose role + universal skills.

    Also exercises --debate-roles which renders the hardcoded AgentRoles
    with universal skills appended via render_prompt.
    """

    def test_prompt_list_yaml_experts(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["prompt", "--list"])
        assert result.exit_code == 0, result.output
        assert "simplicity" in result.output or "modularity" in result.output

    def test_prompt_specific_yaml_expert_includes_universal_skills(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["prompt", "simplicity"])
        assert result.exit_code == 0, result.output
        assert "SOLID + DRY Enforcement" in result.output
        assert "Karpathy Guidelines" in result.output
        assert len(result.output) > 10000

    def test_prompt_debate_role_list(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["prompt", "--debate-roles", "--list"])
        assert result.exit_code == 0, result.output
        # 5 hardcoded debate roles -- at least the Simplicity Critic
        assert "Simplicity Critic" in result.output

    def test_prompt_debate_role_includes_universal_skills(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["prompt", "--debate-roles", "Simplicity Critic"])
        assert result.exit_code == 0, result.output
        # render_prompt should append universal skill bodies
        assert "SOLID + DRY Enforcement" in result.output
        assert "Karpathy Guidelines" in result.output

    def test_prompt_unknown_expert(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["prompt", "no-such-expert"])
        assert result.exit_code == 1
        assert "not found" in result.output
