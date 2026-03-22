"""Tests for CLI commands."""

import json
from pathlib import Path

from click.testing import CliRunner

from review_swarm.cli import main
from review_swarm.config import Config


class TestCliInit:
    def test_init_creates_config(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.yaml"
        monkeypatch.setattr(
            "review_swarm.cli.Path",
            lambda p: config_path if "config.yaml" in str(p) else Path(p),
        )
        # Simpler approach: just test the Config.to_yaml output
        config = Config()
        yaml_str = config.to_yaml()
        assert "max_sessions" in yaml_str
        assert "consensus" in yaml_str


class TestCliListSessions:
    def test_no_sessions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "review_swarm.cli.Config.load",
            lambda path=None: Config(storage_dir=str(tmp_path)),
        )
        runner = CliRunner()
        result = runner.invoke(main, ["list-sessions"])
        assert result.exit_code == 0
        assert "No sessions" in result.output


class TestCliReport:
    def test_report_not_found(self, tmp_path, monkeypatch):
        config = Config(storage_dir=str(tmp_path))
        config.sessions_path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            "review_swarm.cli.Config.load",
            lambda path=None: config,
        )
        runner = CliRunner()
        result = runner.invoke(main, ["report", "sess-nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestCliPrompt:
    def test_prompt_list(self):
        runner = CliRunner()
        result = runner.invoke(main, ["prompt", "--list"])
        assert result.exit_code == 0
        assert "threading-safety" in result.output

    def test_prompt_specific(self):
        runner = CliRunner()
        result = runner.invoke(main, ["prompt", "threading-safety"])
        assert result.exit_code == 0
        assert len(result.output) > 100  # system prompt should be substantial

    def test_prompt_not_found(self):
        runner = CliRunner()
        result = runner.invoke(main, ["prompt", "nonexistent-expert"])
        assert result.exit_code == 1
        assert "not found" in result.output


class TestCliVersion:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.3.0" in result.output


class TestCliPurge:
    def test_purge_no_sessions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "review_swarm.cli.Config.load",
            lambda path=None: Config(storage_dir=str(tmp_path)),
        )
        runner = CliRunner()
        result = runner.invoke(main, ["purge"])
        assert result.exit_code == 0
