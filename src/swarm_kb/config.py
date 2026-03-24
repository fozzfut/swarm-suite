"""Suite-wide configuration for the Swarm knowledge base."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_log = logging.getLogger("swarm_kb.config")

_DEFAULT_ROOT = "~/.swarm-kb"

_DEFAULT_CONFIG: dict = {
    "storage_root": _DEFAULT_ROOT,
    "code_map": {
        "cache_ttl_hours": 1,
        "skip_dirs": [
            "node_modules", ".venv", "venv", "__pycache__", ".git",
            "target", "build", "dist", "vendor", "bin", "obj",
            ".mypy_cache", ".pytest_cache", ".tox",
            ".eggs", "site-packages",
            ".claude", ".worktrees",
        ],
        "max_file_size_mb": 5,
        "source_exts": [
            ".py", ".js", ".ts", ".tsx", ".jsx",
            ".go", ".rs", ".java", ".kt",
            ".cs", ".cpp", ".c", ".h", ".hpp",
            ".rb", ".ex", ".exs", ".swift", ".php",
        ],
    },
    "review": {},
    "fix": {},
    "doc": {},
    "arch": {},
}

TOOL_NAMES = ("review", "fix", "doc", "arch", "spec")


@dataclass
class CodeMapConfig:
    cache_ttl_hours: float = 1.0
    skip_dirs: list[str] = field(default_factory=lambda: list(_DEFAULT_CONFIG["code_map"]["skip_dirs"]))
    max_file_size_mb: float = 5.0
    source_exts: list[str] = field(default_factory=lambda: list(_DEFAULT_CONFIG["code_map"]["source_exts"]))


@dataclass
class SuiteConfig:
    """Central configuration for the Swarm knowledge base."""

    storage_root: str = _DEFAULT_ROOT
    code_map: CodeMapConfig = field(default_factory=CodeMapConfig)
    _tool_configs: dict[str, dict] = field(default_factory=dict)
    _raw: dict = field(default_factory=dict)

    # -- Resolved paths -------------------------------------------------------

    @property
    def kb_root(self) -> Path:
        return Path(self.storage_root).expanduser().resolve()

    def tool_sessions_path(self, tool: str) -> Path:
        return self.kb_root / tool / "sessions"

    @property
    def code_map_path(self) -> Path:
        return self.kb_root / "code-map"

    @property
    def xrefs_path(self) -> Path:
        return self.kb_root / "xrefs"

    @property
    def decisions_path(self) -> Path:
        return self.kb_root / "decisions"

    @property
    def debates_path(self) -> Path:
        return self.kb_root / "debates"

    @property
    def pipelines_path(self) -> Path:
        return self.kb_root / "pipelines"

    @property
    def config_file(self) -> Path:
        return self.kb_root / "config.yaml"

    # -- Tool-specific config access ------------------------------------------

    def tool_config(self, tool: str) -> dict:
        """Get tool-specific config section (or empty dict)."""
        return dict(self._tool_configs.get(tool, {}))

    # -- Load / Save ----------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> SuiteConfig:
        """Load config from YAML file, or return defaults if not found."""
        if path is None:
            path = Path(_DEFAULT_ROOT).expanduser().resolve() / "config.yaml"

        raw: dict = {}
        if path.exists():
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except Exception as exc:
                _log.warning("Failed to load config from %s: %s", path, exc)

        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, raw: dict) -> SuiteConfig:
        cm_raw = raw.get("code_map", {})
        cm = CodeMapConfig(
            cache_ttl_hours=cm_raw.get("cache_ttl_hours", 1.0),
            skip_dirs=cm_raw.get("skip_dirs", list(_DEFAULT_CONFIG["code_map"]["skip_dirs"])),
            max_file_size_mb=cm_raw.get("max_file_size_mb", 5.0),
            source_exts=cm_raw.get("source_exts", list(_DEFAULT_CONFIG["code_map"]["source_exts"])),
        )

        tool_cfgs = {}
        for t in TOOL_NAMES:
            if t in raw and isinstance(raw[t], dict):
                tool_cfgs[t] = raw[t]

        return cls(
            storage_root=raw.get("storage_root", _DEFAULT_ROOT),
            code_map=cm,
            _tool_configs=tool_cfgs,
            _raw=raw,
        )

    def save(self) -> None:
        """Write current config to config.yaml."""
        data = {
            "storage_root": self.storage_root,
            "code_map": {
                "cache_ttl_hours": self.code_map.cache_ttl_hours,
                "skip_dirs": self.code_map.skip_dirs,
                "max_file_size_mb": self.code_map.max_file_size_mb,
                "source_exts": self.code_map.source_exts,
            },
        }
        for t in TOOL_NAMES:
            if t in self._tool_configs:
                data[t] = self._tool_configs[t]

        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        _log.info("Config saved to %s", self.config_file)
