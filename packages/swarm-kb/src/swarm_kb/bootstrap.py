"""Auto-initialization on MCP server startup.

Creates directories, migrates legacy data, generates default config.
"""

from __future__ import annotations

from swarm_core.logging_setup import get_logger

from .config import SuiteConfig, TOOL_NAMES
from .compat import migrate_all

_log = get_logger("kb.bootstrap")


def bootstrap(config: SuiteConfig | None = None) -> SuiteConfig:
    """Initialize the Swarm KB. Called automatically on MCP server start.

    1. Create all directories
    2. Generate config.yaml if absent
    3. Migrate legacy sessions (idempotent)

    Returns the effective SuiteConfig.
    """
    if config is None:
        config = SuiteConfig.load()

    _log.info("Bootstrapping Swarm KB at %s", config.kb_root)

    # 1. Create directory structure
    _ensure_dirs(config)

    # 2. Generate default config if absent
    if not config.config_file.exists():
        config.save()
        _log.info("Generated default config at %s", config.config_file)

    # 3. Migrate legacy data (idempotent -- skips already-migrated sessions)
    try:
        result = migrate_all(config)
        for tool, ids in result.items():
            if ids:
                _log.info("Migrated %d %s session(s): %s", len(ids), tool, ", ".join(ids))
    except Exception as exc:
        _log.warning("Migration failed (non-fatal): %s", exc)

    _log.info("Bootstrap complete")
    return config


def _ensure_dirs(config: SuiteConfig) -> None:
    """Create all KB directories."""
    dirs = [
        config.kb_root,
        config.code_map_path,
        config.xrefs_path,
        config.decisions_path,
        config.debates_path,
        config.pipelines_path,
    ]
    for tool in TOOL_NAMES:
        dirs.append(config.tool_sessions_path(tool))

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        _log.debug("Ensured directory: %s", d)
