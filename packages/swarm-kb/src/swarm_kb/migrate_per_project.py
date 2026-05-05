"""Phase 5 M4 -- migrate legacy global KB layout to per-project layout.

Legacy:
    ~/.swarm-kb/<tool>/sessions/<sid>/
    ~/.swarm-kb/decisions/decisions.jsonl
    ~/.swarm-kb/debates/active/<dbt>/
    ~/.swarm-kb/pipelines/<pid>.json
    ~/.swarm-kb/code-map/<project_hash>/
    ~/.swarm-kb/index/kb.db

New:
    ~/.swarm-kb/projects/<project_hash>/<tool>/sessions/<sid>/
    ~/.swarm-kb/projects/<project_hash>/decisions/decisions.jsonl
    ~/.swarm-kb/projects/<project_hash>/debates/active/<dbt>/
    ~/.swarm-kb/projects/<project_hash>/pipelines/<pid>.json
    ~/.swarm-kb/projects/<project_hash>/code-map/
    ~/.swarm-kb/projects/<project_hash>/index/kb.db   (NOT migrated; rebuilt)

Public entry point: ``run_migration``. Each ``_migrate_*`` helper returns a
small result tuple/dict that the CLI aggregates for the summary print.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import SuiteConfig, TOOL_NAMES
from .paths import project_hash_for
from .session_meta import read_meta

_log = logging.getLogger("swarm_kb.migrate_per_project")

# Sentinel project label for entries without a project_path field.
LEGACY_UNATTRIBUTED_LABEL = "_legacy_unattributed"

# TOOL_NAMES from config includes "runner" which is closed-source.
# Migration walks every other tool in TOOL_NAMES.
_MIGRATABLE_TOOLS = tuple(t for t in TOOL_NAMES if t != "runner")


@dataclass
class MigrationResult:
    """Aggregated migration outcome for the CLI summary."""

    sessions_migrated: int = 0
    sessions_by_project: dict[str, int] = field(default_factory=dict)
    decisions_migrated: int = 0
    debates_migrated: int = 0
    debate_dirs_migrated: int = 0
    pipelines_migrated: int = 0
    code_maps_migrated: int = 0
    vector_index_dropped: bool = False
    # Maps project_hash -> resolved project_path (for the "Migrated projects"
    # section of the summary) -- whatever ended up with content.
    projects: dict[str, str] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------


def _resolve_project_label(project_path: str, default_project: str | None) -> str:
    """Return the effective project_path string used for grouping.

    - If ``project_path`` is non-empty, return it (resolved if it's a real path).
    - If empty and ``default_project`` is given, return it (resolved).
    - Else return the synthetic ``_legacy_unattributed`` sentinel string,
      which ``project_hash_for`` will hash like any other path.
    """
    if project_path:
        try:
            return str(Path(project_path).resolve())
        except OSError:
            return project_path
    if default_project:
        try:
            return str(Path(default_project).resolve())
        except OSError:
            return default_project
    return LEGACY_UNATTRIBUTED_LABEL


def _track_project(result: MigrationResult, project_label: str) -> str:
    """Record a project hash in the result map and return the hash."""
    h = project_hash_for(project_label)
    result.projects.setdefault(h, project_label)
    return h


# ---------------------------------------------------------------------------
# Session migration
# ---------------------------------------------------------------------------


def _migrate_sessions(
    config: SuiteConfig,
    result: MigrationResult,
    *,
    dry_run: bool,
    keep_legacy: bool,
    default_project: str | None,
) -> None:
    """Move per-tool session directories into projects/<hash>/<tool>/sessions/."""
    for tool in _MIGRATABLE_TOOLS:
        legacy_dir = config.tool_sessions_path(tool)
        if not legacy_dir.exists():
            continue

        for session_dir in sorted(legacy_dir.iterdir()):
            if not session_dir.is_dir():
                continue

            meta = read_meta(session_dir) or {}
            if meta.get("migrated_from_legacy") is True:
                _log.debug("Session %s already marked migrated; skipping", session_dir.name)
                continue

            project_path = meta.get("project_path", "") or ""
            project_label = _resolve_project_label(project_path, default_project)
            project_hash = _track_project(result, project_label)

            target = config.project_tool_sessions_path(project_label, tool) / session_dir.name
            if target.exists():
                msg = f"target {target} already exists; skipping {tool}/{session_dir.name}"
                _log.info(msg)
                result.skipped.append(msg)
                continue

            if dry_run:
                action = "copy" if keep_legacy else "move"
                _log.info("[dry-run] would %s %s -> %s", action, session_dir, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                if keep_legacy:
                    shutil.copytree(session_dir, target)
                else:
                    shutil.move(str(session_dir), str(target))
                _mark_session_migrated(target)

            result.sessions_migrated += 1
            result.sessions_by_project[project_hash] = (
                result.sessions_by_project.get(project_hash, 0) + 1
            )


def _mark_session_migrated(session_dir: Path) -> None:
    """Stamp meta.json with ``migrated_from_legacy: true`` for idempotency."""
    meta_path = session_dir / "meta.json"
    if not meta_path.exists():
        # Create a minimal meta so re-runs are idempotent.
        from swarm_core.io import atomic_write_text
        atomic_write_text(
            meta_path,
            json.dumps(
                {
                    "migrated_from_legacy": True,
                    "migration_date": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
        )
        return
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            return
    except (json.JSONDecodeError, OSError):
        return
    meta["migrated_from_legacy"] = True
    meta["migration_date"] = datetime.now(timezone.utc).isoformat()
    from swarm_core.io import atomic_write_text
    atomic_write_text(meta_path, json.dumps(meta, indent=2))


# ---------------------------------------------------------------------------
# JSONL splitting (decisions, debates ledger)
# ---------------------------------------------------------------------------


def _atomic_write_jsonl(path: Path, lines: list[str]) -> None:
    """Atomically write JSONL lines to path (mirrors decision_store._atomic_write)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = ("\n".join(lines) + "\n") if lines else ""
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        fh = os.fdopen(tmp_fd, "w", encoding="utf-8")
        with fh:
            fh.write(content)
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.close(tmp_fd)
        except OSError:
            pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_jsonl_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            _log.warning("Skipping corrupt JSONL line in %s: %s", path, exc)
    return out


def _merge_jsonl_by_id(
    target: Path, new_entries: list[dict], *, dry_run: bool,
) -> int:
    """Append new_entries to target JSONL, dedupe by ``id`` field.

    Returns the number of *newly added* entries. Re-runs are safe: entries
    whose ``id`` is already present at target are dropped.
    """
    if not new_entries:
        return 0
    existing = _read_jsonl_lines(target)
    existing_ids = {e.get("id") for e in existing if e.get("id")}
    to_add = [
        e for e in new_entries
        if not e.get("id") or e.get("id") not in existing_ids
    ]
    if not to_add:
        return 0
    if dry_run:
        _log.info("[dry-run] would append %d entry/ies to %s", len(to_add), target)
        return len(to_add)
    merged_lines = [json.dumps(e) for e in (existing + to_add)]
    _atomic_write_jsonl(target, merged_lines)
    return len(to_add)


def _migrate_decisions(
    config: SuiteConfig,
    result: MigrationResult,
    *,
    dry_run: bool,
    keep_legacy: bool,
    default_project: str | None,
) -> None:
    """Split legacy decisions.jsonl into per-project files."""
    legacy = config.decisions_path / "decisions.jsonl"
    entries = _read_jsonl_lines(legacy)
    if not entries:
        return

    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        project_label = _resolve_project_label(
            str(entry.get("project_path", "") or ""),
            default_project,
        )
        grouped.setdefault(project_label, []).append(entry)

    for project_label, group in grouped.items():
        _track_project(result, project_label)
        target = config.project_decisions_path(project_label) / "decisions.jsonl"
        added = _merge_jsonl_by_id(target, group, dry_run=dry_run)
        result.decisions_migrated += added


def _migrate_debates_ledger(
    config: SuiteConfig,
    result: MigrationResult,
    *,
    dry_run: bool,
    default_project: str | None,
) -> None:
    """Split legacy debates/debates.jsonl into per-project files."""
    legacy = config.debates_path / "debates.jsonl"
    entries = _read_jsonl_lines(legacy)
    if not entries:
        return

    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        project_label = _resolve_project_label(
            str(entry.get("project_path", "") or ""),
            default_project,
        )
        grouped.setdefault(project_label, []).append(entry)

    for project_label, group in grouped.items():
        _track_project(result, project_label)
        target = config.project_debates_path(project_label) / "debates.jsonl"
        added = _merge_jsonl_by_id(target, group, dry_run=dry_run)
        result.debates_migrated += added


def _migrate_active_debates(
    config: SuiteConfig,
    result: MigrationResult,
    *,
    dry_run: bool,
    keep_legacy: bool,
    default_project: str | None,
) -> None:
    """Move ``debates/active/<dbt>/`` directories into per-project debates/active/."""
    legacy_active = config.debates_path / "active"
    if not legacy_active.exists():
        return

    for debate_dir in sorted(legacy_active.iterdir()):
        if not debate_dir.is_dir():
            continue

        debate_json = debate_dir / "debate.json"
        project_path = ""
        if debate_json.exists():
            try:
                data = json.loads(debate_json.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    project_path = str(data.get("project_path", "") or "")
            except json.JSONDecodeError as exc:
                _log.warning("Skipping debate %s (corrupt JSON): %s", debate_dir, exc)
                continue

        project_label = _resolve_project_label(project_path, default_project)
        _track_project(result, project_label)

        target = config.project_debates_path(project_label) / "active" / debate_dir.name
        if target.exists():
            msg = f"target debate dir {target} already exists; skipping {debate_dir.name}"
            _log.info(msg)
            result.skipped.append(msg)
            continue

        if dry_run:
            action = "copy" if keep_legacy else "move"
            _log.info("[dry-run] would %s %s -> %s", action, debate_dir, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if keep_legacy:
                shutil.copytree(debate_dir, target)
            else:
                shutil.move(str(debate_dir), str(target))

        result.debate_dirs_migrated += 1


def _migrate_debates(
    config: SuiteConfig,
    result: MigrationResult,
    *,
    dry_run: bool,
    keep_legacy: bool,
    default_project: str | None,
) -> None:
    """Migrate both the debates ledger and active debate directories."""
    _migrate_debates_ledger(
        config, result,
        dry_run=dry_run, default_project=default_project,
    )
    _migrate_active_debates(
        config, result,
        dry_run=dry_run, keep_legacy=keep_legacy, default_project=default_project,
    )


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------


def _migrate_pipelines(
    config: SuiteConfig,
    result: MigrationResult,
    *,
    dry_run: bool,
    keep_legacy: bool,
    default_project: str | None,
) -> None:
    """Move ``pipelines/<pid>.json`` into per-project pipelines dirs."""
    legacy_dir = config.pipelines_path
    if not legacy_dir.exists():
        return

    for pipe_file in sorted(legacy_dir.glob("pipe-*.json")):
        try:
            data = json.loads(pipe_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("Skipping pipeline %s (corrupt JSON): %s", pipe_file, exc)
            continue
        project_path = str(data.get("project_path", "") or "") if isinstance(data, dict) else ""

        project_label = _resolve_project_label(project_path, default_project)
        _track_project(result, project_label)

        target = config.project_pipelines_path(project_label) / pipe_file.name
        if target.exists():
            msg = f"target pipeline {target} already exists; skipping {pipe_file.name}"
            _log.info(msg)
            result.skipped.append(msg)
            continue

        if dry_run:
            action = "copy" if keep_legacy else "move"
            _log.info("[dry-run] would %s %s -> %s", action, pipe_file, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            if keep_legacy:
                shutil.copy2(pipe_file, target)
            else:
                shutil.move(str(pipe_file), str(target))

        result.pipelines_migrated += 1


# ---------------------------------------------------------------------------
# Code map
# ---------------------------------------------------------------------------


def _migrate_code_map(
    config: SuiteConfig,
    result: MigrationResult,
    *,
    dry_run: bool,
    keep_legacy: bool,
) -> None:
    """Move ``code-map/<project_hash>/`` into ``projects/<hash>/code-map/``."""
    legacy_dir = config.code_map_path
    if not legacy_dir.exists():
        return

    for hashed_dir in sorted(legacy_dir.iterdir()):
        if not hashed_dir.is_dir():
            continue
        project_hash = hashed_dir.name

        target_root = config.projects_root / project_hash / "code-map"
        if target_root.exists():
            msg = f"target code-map {target_root} already exists; skipping"
            _log.info(msg)
            result.skipped.append(msg)
            continue

        # Track the project hash even though we can't resolve back to a real
        # path -- the hash is what already lives on disk.
        result.projects.setdefault(project_hash, f"<hashed:{project_hash}>")

        if dry_run:
            action = "copy" if keep_legacy else "move"
            _log.info("[dry-run] would %s %s -> %s", action, hashed_dir, target_root)
        else:
            target_root.parent.mkdir(parents=True, exist_ok=True)
            if keep_legacy:
                shutil.copytree(hashed_dir, target_root)
            else:
                shutil.move(str(hashed_dir), str(target_root))

        result.code_maps_migrated += 1


# ---------------------------------------------------------------------------
# Vector index
# ---------------------------------------------------------------------------


def _drop_legacy_vector_index(
    config: SuiteConfig, *, dry_run: bool, keep_legacy: bool,
) -> bool:
    """Drop the legacy global vector index.

    The per-project rebuild requires fresh DBs, so we either delete the
    legacy file (default) or rename to ``.bak`` (when --keep-legacy is set).
    Returns True if a file was found.
    """
    legacy = config.vector_index_path
    if not legacy.exists():
        return False
    if dry_run:
        _log.info("[dry-run] would drop legacy vector index at %s", legacy)
        return True
    if keep_legacy:
        backup = legacy.with_suffix(legacy.suffix + ".bak")
        if backup.exists():
            backup.unlink()
        legacy.rename(backup)
        _log.info("Renamed legacy vector index %s -> %s", legacy, backup)
    else:
        legacy.unlink()
        _log.info("Deleted legacy vector index %s", legacy)
    return True


# ---------------------------------------------------------------------------
# Project meta
# ---------------------------------------------------------------------------


def _write_project_meta(
    config: SuiteConfig,
    *,
    project_hash: str,
    project_label: str,
    dry_run: bool,
) -> None:
    """Write/update projects/<hash>/meta.json with migration markers."""
    meta_path = config.projects_root / project_hash / "meta.json"
    now = datetime.now(timezone.utc).isoformat()

    existing: dict = {}
    if meta_path.exists():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except (json.JSONDecodeError, OSError):
            existing = {}

    meta = dict(existing)
    meta.setdefault("project_path", project_label)
    meta.setdefault("created_at", now)
    meta["last_used_at"] = now
    meta["migrated_from_legacy"] = True
    meta["migration_date"] = now

    if dry_run:
        _log.info("[dry-run] would write %s", meta_path)
        return

    from swarm_core.io import atomic_write_text
    atomic_write_text(meta_path, json.dumps(meta, indent=2))


# ---------------------------------------------------------------------------
# Cleanup (--finalize)
# ---------------------------------------------------------------------------


def cleanup_legacy(config: SuiteConfig, *, dry_run: bool = False) -> list[Path]:
    """Delete legacy global directories that are now superseded by per-project layout.

    Called by the ``--finalize`` flag once the user has verified the
    migration. Never deletes ``xrefs/`` (still global) or ``projects/``,
    ``config.yaml``.
    """
    targets = [
        config.code_map_path,
        config.decisions_path,
        config.debates_path,
        config.pipelines_path,
        config.kb_root / "index",
    ]
    for tool in _MIGRATABLE_TOOLS:
        targets.append(config.kb_root / tool)

    deleted: list[Path] = []
    for path in targets:
        if not path.exists():
            continue
        if dry_run:
            _log.info("[dry-run] would delete legacy path %s", path)
            deleted.append(path)
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            deleted.append(path)
            _log.info("Deleted legacy path %s", path)
        except OSError as exc:
            _log.warning("Failed to delete %s: %s", path, exc)
    return deleted


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def run_migration(
    config: SuiteConfig,
    *,
    dry_run: bool = False,
    keep_legacy: bool = False,
    default_project: str | None = None,
) -> MigrationResult:
    """Execute the full per-project migration. Idempotent on re-run.

    Args:
        config: Loaded ``SuiteConfig``.
        dry_run: If True, log intended actions without writing.
        keep_legacy: If True, copy instead of move (legacy paths remain).
        default_project: Fallback project_path for entries without one.
    """
    result = MigrationResult()

    _migrate_sessions(
        config, result,
        dry_run=dry_run, keep_legacy=keep_legacy, default_project=default_project,
    )
    _migrate_decisions(
        config, result,
        dry_run=dry_run, keep_legacy=keep_legacy, default_project=default_project,
    )
    _migrate_debates(
        config, result,
        dry_run=dry_run, keep_legacy=keep_legacy, default_project=default_project,
    )
    _migrate_pipelines(
        config, result,
        dry_run=dry_run, keep_legacy=keep_legacy, default_project=default_project,
    )
    _migrate_code_map(
        config, result,
        dry_run=dry_run, keep_legacy=keep_legacy,
    )
    result.vector_index_dropped = _drop_legacy_vector_index(
        config, dry_run=dry_run, keep_legacy=keep_legacy,
    )

    # Stamp meta.json on every project that ended up with content.
    for project_hash, project_label in result.projects.items():
        _write_project_meta(
            config,
            project_hash=project_hash,
            project_label=project_label,
            dry_run=dry_run,
        )

    return result
