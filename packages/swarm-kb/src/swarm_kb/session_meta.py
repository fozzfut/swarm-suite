"""Generic session metadata reader for any tool's sessions."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import TOOL_NAMES, SuiteConfig

_log = logging.getLogger("swarm_kb.session_meta")


def read_meta(session_dir: Path) -> dict | None:
    """Read meta.json from a session directory. Returns None on missing/corrupt/non-dict JSON."""
    meta_path = session_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning("Failed to read %s: %s", meta_path, exc)
        return None
    if not isinstance(raw, dict):
        _log.warning("%s is not a JSON object (got %s); ignoring", meta_path, type(raw).__name__)
        return None
    return raw


def list_sessions(
    config: SuiteConfig,
    tool: str | None = None,
) -> list[dict]:
    """List sessions across tools, returning metadata for each.

    If tool is specified, only list sessions for that tool.
    Returns list of dicts with 'tool', 'session_id', 'session_dir', and meta fields.
    """
    tools = [tool] if tool and tool in TOOL_NAMES else list(TOOL_NAMES)
    results: list[dict] = []

    for t in tools:
        sessions_dir = config.tool_sessions_path(t)
        if not sessions_dir.exists():
            continue

        for entry in sorted(sessions_dir.iterdir()):
            if not entry.is_dir():
                continue

            meta = read_meta(entry)
            info = {
                "tool": t,
                "session_id": entry.name,
                "session_dir": str(entry),
            }
            if meta:
                info.update(meta)
            results.append(info)

    return results


def count_sessions(config: SuiteConfig) -> dict[str, int]:
    """Count sessions per tool."""
    counts: dict[str, int] = {}
    for t in TOOL_NAMES:
        sessions_dir = config.tool_sessions_path(t)
        if sessions_dir.exists():
            counts[t] = sum(1 for e in sessions_dir.iterdir() if e.is_dir())
        else:
            counts[t] = 0
    return counts
