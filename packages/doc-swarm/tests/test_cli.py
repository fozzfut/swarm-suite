"""Tests for DocSwarm CLI."""

from click.testing import CliRunner
from doc_swarm.cli import main


class TestCliVersion:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "version" in result.output


class TestCliScan:
    def test_scan(self, sample_project):
        runner = CliRunner()
        result = runner.invoke(main, ["scan", str(sample_project), "--scope", "src/"])
        assert result.exit_code == 0
        assert "Engine" in result.output
        assert "create_engine" in result.output


class TestCliGenerate:
    def test_generate(self, sample_project):
        runner = CliRunner()
        result = runner.invoke(main, [
            "generate", str(sample_project),
            "--scope", "src/",
            "--output", "docs",
        ])
        assert result.exit_code == 0
        assert "Written" in result.output

        # Check files were created
        docs_dir = sample_project / "docs"
        assert docs_dir.exists()
        assert (docs_dir / "HOME.md").exists()
        assert (docs_dir / "INDEX.md").exists()
        assert (docs_dir / "api").exists()


class TestCliPrompt:
    """`doc-swarm prompt <expert>` should compose role + skills."""

    def test_prompt_list(self):
        runner = CliRunner()
        result = runner.invoke(main, ["prompt", "--list"])
        assert result.exit_code == 0, result.output
        assert "api-reference" in result.output or "tutorial-writer" in result.output

    def test_prompt_specific_includes_universal_skills(self):
        runner = CliRunner()
        result = runner.invoke(main, ["prompt", "api-reference"])
        assert result.exit_code == 0, result.output
        assert "SOLID + DRY Enforcement" in result.output
        assert "Karpathy Guidelines" in result.output
        assert "Self Review" in result.output
        assert len(result.output) > 10000

    def test_prompt_unknown_expert(self):
        runner = CliRunner()
        result = runner.invoke(main, ["prompt", "nonexistent-expert"])
        assert result.exit_code == 1
        assert "not found" in result.output
