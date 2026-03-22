"""Migration utilities -- copy sessions from legacy paths to ~/.swarm-kb/."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .config import SuiteConfig
from .paths import old_doc_swarm_path, old_review_swarm_path

_log = logging.getLogger("swarm_kb.compat")


def migrate_review_swarm(config: SuiteConfig) -> list[str]:
    """Copy ReviewSwarm sessions from ~/.review-swarm/sessions/ to KB.

    Returns list of migrated session IDs.
    """
    old_sessions = old_review_swarm_path() / "sessions"
    new_sessions = config.tool_sessions_path("review")
    return _copy_sessions(old_sessions, new_sessions, "review")


def migrate_doc_swarm(config: SuiteConfig) -> list[str]:
    """Copy DocSwarm sessions from ~/.doc-swarm/sessions/ to KB."""
    old_sessions = old_doc_swarm_path() / "sessions"
    new_sessions = config.tool_sessions_path("doc")
    return _copy_sessions(old_sessions, new_sessions, "doc")


def migrate_arch_swarm(config: SuiteConfig, project_dirs: list[Path] | None = None) -> list[str]:
    """Migrate ArchSwarm sessions from .archswarm_sessions/ directories.

    ArchSwarm stores sessions in project-local .archswarm_sessions/ dirs.
    We need to know which project dirs to scan. If not provided, skips.

    Converts UUID-based IDs to arch-YYYY-MM-DD-NNN format.
    """
    if not project_dirs:
        _log.info("No project directories provided for ArchSwarm migration, skipping")
        return []

    new_sessions = config.tool_sessions_path("arch")
    new_sessions.mkdir(parents=True, exist_ok=True)
    migrated: list[str] = []

    for proj_dir in project_dirs:
        old_dir = proj_dir / ".archswarm_sessions"
        if not old_dir.exists():
            continue

        for json_file in sorted(old_dir.glob("*.json")):
            old_id = json_file.stem
            md_file = old_dir / f"{old_id}.md"

            # Generate new session ID
            new_id = _generate_arch_session_id(json_file, new_sessions)
            new_dir = new_sessions / new_id

            if new_dir.exists():
                _log.debug("ArchSwarm session %s already migrated, skipping", new_id)
                continue

            new_dir.mkdir(parents=True, exist_ok=True)

            # Read old metadata
            try:
                old_meta = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                old_meta = {}

            # Write new meta.json
            meta = {
                "schema_version": 1,
                "tool": "arch",
                "session_id": new_id,
                "old_id": old_id,
                "project_path": str(proj_dir),
                "topic": old_meta.get("topic", ""),
                "status": old_meta.get("status", "completed"),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            (new_dir / "meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )

            # Copy debate data
            (new_dir / "debate.json").write_text(
                json.dumps(old_meta, indent=2), encoding="utf-8"
            )

            if md_file.exists():
                shutil.copy2(md_file, new_dir / "transcript.md")

            migrated.append(new_id)
            _log.info("Migrated ArchSwarm session %s -> %s", old_id, new_id)

    return migrated


def migrate_all(config: SuiteConfig, arch_project_dirs: list[Path] | None = None) -> dict[str, list[str]]:
    """Run all migrations. Returns dict of tool -> list of migrated session IDs."""
    result: dict[str, list[str]] = {}

    review_ids = migrate_review_swarm(config)
    if review_ids:
        result["review"] = review_ids

    doc_ids = migrate_doc_swarm(config)
    if doc_ids:
        result["doc"] = doc_ids

    arch_ids = migrate_arch_swarm(config, arch_project_dirs)
    if arch_ids:
        result["arch"] = arch_ids

    total = sum(len(v) for v in result.values())
    if total:
        _log.info("Migration complete: %d sessions total", total)
    else:
        _log.info("No sessions to migrate")

    return result


# -- Internal helpers ---------------------------------------------------------


def _copy_sessions(old_dir: Path, new_dir: Path, tool: str) -> list[str]:
    """Copy session directories from old location to new."""
    if not old_dir.exists():
        _log.debug("No legacy %s sessions at %s", tool, old_dir)
        return []

    new_dir.mkdir(parents=True, exist_ok=True)
    migrated: list[str] = []

    for entry in sorted(old_dir.iterdir()):
        if not entry.is_dir():
            continue

        dest = new_dir / entry.name
        if dest.exists():
            _log.debug("Session %s already exists in KB, skipping", entry.name)
            continue

        try:
            shutil.copytree(entry, dest)
            migrated.append(entry.name)
            _log.info("Migrated %s session: %s", tool, entry.name)
        except Exception as exc:
            _log.warning("Failed to migrate %s session %s: %s", tool, entry.name, exc)

    return migrated


def _generate_arch_session_id(json_file: Path, sessions_dir: Path) -> str:
    """Generate arch-YYYY-MM-DD-NNN format session ID."""
    try:
        mtime = datetime.fromtimestamp(json_file.stat().st_mtime, timezone.utc)
    except Exception:
        mtime = datetime.now(timezone.utc)

    date_str = mtime.strftime("%Y-%m-%d")
    prefix = f"arch-{date_str}"

    existing = [d.name for d in sessions_dir.iterdir() if d.is_dir() and d.name.startswith(prefix)]
    seq = len(existing) + 1
    return f"{prefix}-{seq:03d}"
