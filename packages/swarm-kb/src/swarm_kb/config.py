"""Suite-wide configuration for the Swarm knowledge base."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from swarm_core.logging_setup import get_logger

_log = get_logger("kb.config")

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
    "embedding": {
        # Empty provider disables semantic indexing.
        # Set to "local" + install `swarm-kb[embed-local]` to enable.
        "provider": "",
        "model": "intfloat/multilingual-e5-small",
    },
    "review": {},
    "fix": {},
    "doc": {},
    "arch": {},
}

TOOL_NAMES = ("review", "fix", "doc", "arch", "spec",
              "idea", "plan", "harden", "release",
              "monitor",  # trace analyzer (monitor-swarm)
              "runner")  # closed-source overnight runtime (private repo)


@dataclass
class CodeMapConfig:
    cache_ttl_hours: float = 1.0
    skip_dirs: list[str] = field(default_factory=lambda: list(_DEFAULT_CONFIG["code_map"]["skip_dirs"]))
    max_file_size_mb: float = 5.0
    source_exts: list[str] = field(default_factory=lambda: list(_DEFAULT_CONFIG["code_map"]["source_exts"]))


@dataclass
class EmbeddingConfig:
    """Configuration for the optional vector memory layer (adr-15bde0ae)."""

    provider: str = ""  # "" disables; "local" uses sentence-transformers
    model: str = "intfloat/multilingual-e5-small"


@dataclass
class SuiteConfig:
    """Central configuration for the Swarm knowledge base."""

    storage_root: str = _DEFAULT_ROOT
    code_map: CodeMapConfig = field(default_factory=CodeMapConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    _tool_configs: dict[str, dict] = field(default_factory=dict)
    _raw: dict = field(default_factory=dict)

    # -- Resolved paths -------------------------------------------------------

    @property
    def kb_root(self) -> Path:
        return Path(self.storage_root).expanduser().resolve()

    # ── Legacy global paths (Phase 5 backwards-compat) ─────────────────
    # All `*_path` accessors below return GLOBAL paths under kb_root.
    # New code SHOULD prefer `project_*` variants (per-project layout).
    # See docs/architecture/per-project-storage.md (Phase 5 ADR).

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
    def vector_index_path(self) -> Path:
        """Path to the GLOBAL sqlite + sqlite-vec materialized index file.

        Deprecated for new code -- use ``project_vector_index_path`` to
        get a per-project index that doesn't leak findings across
        unrelated projects.
        """
        return self.kb_root / "index" / "kb.db"

    @property
    def config_file(self) -> Path:
        return self.kb_root / "config.yaml"

    # ── Per-project paths (Phase 5) ──────────────────────────────────
    # The new layout lives under kb_root/projects/<project_hash>/ so that
    # findings, decisions, debates, vector index, pipelines, etc. are
    # cleanly isolated per project. project_hash_for() is in paths.py
    # and produces a stable 16-char SHA-256 prefix from the resolved
    # absolute project path.

    @property
    def projects_root(self) -> Path:
        """Top-level container for per-project storage."""
        return self.kb_root / "projects"

    def project_root(self, project_path: str | Path) -> Path:
        """Per-project storage root: kb_root/projects/<project_hash>/."""
        from .paths import project_hash_for
        return self.projects_root / project_hash_for(project_path)

    def project_tool_sessions_path(
        self, project_path: str | Path, tool: str,
    ) -> Path:
        return self.project_root(project_path) / tool / "sessions"

    def project_decisions_path(self, project_path: str | Path) -> Path:
        return self.project_root(project_path) / "decisions"

    def project_debates_path(self, project_path: str | Path) -> Path:
        return self.project_root(project_path) / "debates"

    def project_pipelines_path(self, project_path: str | Path) -> Path:
        return self.project_root(project_path) / "pipelines"

    def project_code_map_path(self, project_path: str | Path) -> Path:
        return self.project_root(project_path) / "code-map"

    def project_xrefs_path(self, project_path: str | Path) -> Path:
        return self.project_root(project_path) / "xrefs"

    def project_vector_index_path(self, project_path: str | Path) -> Path:
        return self.project_root(project_path) / "index" / "kb.db"

    def project_meta_path(self, project_path: str | Path) -> Path:
        """meta.json carrying original project_path, created_at, last_used_at."""
        return self.project_root(project_path) / "meta.json"

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

        emb_raw = raw.get("embedding", {}) or {}
        emb = EmbeddingConfig(
            provider=str(emb_raw.get("provider") or ""),
            model=str(emb_raw.get("model") or _DEFAULT_CONFIG["embedding"]["model"]),
        )

        tool_cfgs = {}
        for t in TOOL_NAMES:
            if t in raw and isinstance(raw[t], dict):
                tool_cfgs[t] = raw[t]

        return cls(
            storage_root=raw.get("storage_root", _DEFAULT_ROOT),
            code_map=cm,
            embedding=emb,
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
            "embedding": {
                "provider": self.embedding.provider,
                "model": self.embedding.model,
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
