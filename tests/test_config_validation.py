"""Tests for Config validation and serialization."""

import pytest
import yaml

from review_swarm.config import Config


class TestConfigValidation:
    def test_valid_config_loads(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump({
            "max_sessions": 10,
            "default_format": "json",
            "consensus": {"confirm_threshold": 3},
        }))
        config = Config.load(cfg_file)
        assert config.max_sessions == 10
        assert config.default_format == "json"
        assert config.consensus.confirm_threshold == 3

    def test_invalid_max_sessions_string(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump({"max_sessions": "many"}))
        with pytest.raises(ValueError, match="max_sessions"):
            Config.load(cfg_file)

    def test_invalid_max_sessions_zero(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump({"max_sessions": 0}))
        with pytest.raises(ValueError, match="max_sessions"):
            Config.load(cfg_file)

    def test_invalid_default_format(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump({"default_format": "xml"}))
        with pytest.raises(ValueError, match="default_format"):
            Config.load(cfg_file)

    def test_invalid_confirm_threshold(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump({"consensus": {"confirm_threshold": 0}}))
        with pytest.raises(ValueError, match="confirm_threshold"):
            Config.load(cfg_file)

    def test_invalid_consensus_not_dict(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml.dump({"consensus": "bad"}))
        with pytest.raises(ValueError, match="consensus"):
            Config.load(cfg_file)

    def test_missing_file_returns_defaults(self, tmp_path):
        config = Config.load(tmp_path / "nonexistent.yaml")
        assert config.max_sessions == 50
        assert config.default_format == "markdown"

    def test_empty_file_returns_defaults(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("")
        config = Config.load(cfg_file)
        assert config.max_sessions == 50


class TestConfigToYaml:
    def test_roundtrip(self):
        config = Config()
        yaml_str = config.to_yaml()
        data = yaml.safe_load(yaml_str)
        assert data["max_sessions"] == 50
        assert data["default_format"] == "markdown"
        assert data["consensus"]["confirm_threshold"] == 2
        assert data["experts"]["auto_suggest"] is True
