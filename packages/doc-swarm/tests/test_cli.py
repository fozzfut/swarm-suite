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
