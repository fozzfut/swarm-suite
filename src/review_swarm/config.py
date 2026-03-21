"""Global configuration loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ConsensusConfig:
    confirm_threshold: int = 2
    auto_close_duplicates: bool = True


@dataclass
class ExpertsConfig:
    custom_dir: str = "~/.review-swarm/custom-experts"
    auto_suggest: bool = True


@dataclass
class Config:
    storage_dir: str | Path = "~/.review-swarm"
    max_sessions: int = 50
    default_format: str = "markdown"
    consensus: ConsensusConfig = field(default_factory=ConsensusConfig)
    experts: ExpertsConfig = field(default_factory=ExpertsConfig)

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir).expanduser()

    @property
    def sessions_path(self) -> Path:
        return self.storage_path / "sessions"

    @property
    def custom_experts_path(self) -> Path:
        return Path(self.experts.custom_dir).expanduser()

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        if path is None:
            path = Path("~/.review-swarm/config.yaml").expanduser()
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        errors = cls._validate(data)
        if errors:
            raise ValueError(
                f"Invalid config ({path}):\n" + "\n".join(f"  - {e}" for e in errors)
            )
        consensus = ConsensusConfig(**data.get("consensus", {}))
        experts = ExpertsConfig(**data.get("experts", {}))
        return cls(
            storage_dir=data.get("storage_dir", "~/.review-swarm"),
            max_sessions=data.get("max_sessions", 50),
            default_format=data.get("default_format", "markdown"),
            consensus=consensus,
            experts=experts,
        )

    @staticmethod
    def _validate(data: dict) -> list[str]:
        """Validate config values. Returns list of error messages."""
        errors: list[str] = []
        if "max_sessions" in data:
            v = data["max_sessions"]
            if not isinstance(v, int) or v < 1:
                errors.append(f"max_sessions must be a positive integer, got {v!r}")
        if "default_format" in data:
            v = data["default_format"]
            if v not in ("markdown", "json"):
                errors.append(f"default_format must be 'markdown' or 'json', got {v!r}")
        if "consensus" in data:
            c = data["consensus"]
            if not isinstance(c, dict):
                errors.append(f"consensus must be a mapping, got {type(c).__name__}")
            else:
                if "confirm_threshold" in c:
                    t = c["confirm_threshold"]
                    if not isinstance(t, int) or t < 1:
                        errors.append(f"consensus.confirm_threshold must be >= 1, got {t!r}")
        return errors

    def to_yaml(self) -> str:
        """Serialize config to YAML string."""
        data = {
            "storage_dir": str(self.storage_dir),
            "max_sessions": self.max_sessions,
            "default_format": self.default_format,
            "consensus": {
                "confirm_threshold": self.consensus.confirm_threshold,
                "auto_close_duplicates": self.consensus.auto_close_duplicates,
            },
            "experts": {
                "custom_dir": self.experts.custom_dir,
                "auto_suggest": self.experts.auto_suggest,
            },
        }
        return yaml.dump(data, default_flow_style=False, sort_keys=False)
