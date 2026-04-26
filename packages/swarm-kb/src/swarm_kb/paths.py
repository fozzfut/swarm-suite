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
    """Return code-map directory for a given project (identified by path hash)."""
    if config is None:
        config = SuiteConfig()
    project_hash = project_hash_for(project_path)
    return config.code_map_path / project_hash


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
