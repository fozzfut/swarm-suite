"""Path utilities for the Swarm knowledge base."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .config import SuiteConfig


def kb_root(config: SuiteConfig | None = None) -> Path:
    """Return the resolved KB root directory."""
    if config is None:
        config = SuiteConfig()
    return config.kb_root


def tool_sessions_path(tool: str, config: SuiteConfig | None = None) -> Path:
    """Return sessions directory for a specific tool."""
    if config is None:
        config = SuiteConfig()
    return config.tool_sessions_path(tool)


def code_map_path(project_path: str | Path, config: SuiteConfig | None = None) -> Path:
    """Return code-map directory for a given project (identified by path hash).

    Phase 5: under the new per-project layout, prefer
    ``config.project_code_map_path(project_path)`` which lives inside the
    project's own root. This legacy function still resolves to the global
    `code-map/<hash>/` path for backwards compat during migration.
    """
    if config is None:
        config = SuiteConfig()
    project_hash = project_hash_for(project_path)
    return config.code_map_path / project_hash


def project_root(project_path: str | Path, config: SuiteConfig | None = None) -> Path:
    """Free-standing wrapper for ``SuiteConfig.project_root``."""
    if config is None:
        config = SuiteConfig()
    return config.project_root(project_path)


def project_tool_sessions_path(
    project_path: str | Path, tool: str,
    config: SuiteConfig | None = None,
) -> Path:
    """Per-project session directory for a tool (Phase 5)."""
    if config is None:
        config = SuiteConfig()
    return config.project_tool_sessions_path(project_path, tool)


def project_hash_for(project_path: str | Path) -> str:
    """Generate a stable hash for a project path.

    Uses the normalized absolute path so the same project always maps
    to the same code-map directory regardless of CWD.
    """
    norm = str(Path(project_path).resolve()).replace("\\", "/").rstrip("/")
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def old_review_swarm_path() -> Path:
    """Legacy ReviewSwarm storage path."""
    return Path("~/.review-swarm").expanduser().resolve()


def old_doc_swarm_path() -> Path:
    """Legacy DocSwarm storage path."""
    return Path("~/.doc-swarm").expanduser().resolve()
