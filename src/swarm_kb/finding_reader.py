"""Read-only access to ReviewSwarm findings + mark_fixed with file lock."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import SuiteConfig

_log = logging.getLogger("swarm_kb.finding_reader")


class FindingReader:
    """Read-only access to a ReviewSwarm session's findings.jsonl.

    Also provides mark_fixed() for cross-tool status updates
    with file-level locking for cross-process safety.
    """

    def __init__(self, session_dir: Path) -> None:
        self._session_dir = Path(session_dir)
        self._findings_path = self._session_dir / "findings.jsonl"
        self._lock = threading.Lock()

    def exists(self) -> bool:
        return self._findings_path.exists()

    def read_all(self) -> list[dict]:
        """Read all findings as raw dicts."""
        if not self._findings_path.exists():
            return []

        findings = []
        with self._lock:
            for line in self._findings_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    findings.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    _log.warning("Skipping corrupt line in %s: %s", self._findings_path, exc)
        return findings

    def get_by_id(self, finding_id: str) -> dict | None:
        """Get a specific finding by ID."""
        for f in self.read_all():
            if f.get("id") == finding_id:
                return f
        return None

    def search(
        self,
        *,
        file: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        min_confidence: float | None = None,
    ) -> list[dict]:
        """Search findings with optional filters."""
        results = self.read_all()
        if file:
            results = [f for f in results if f.get("file") == file]
        if severity:
            results = [f for f in results if f.get("severity") == severity]
        if status:
            results = [f for f in results if f.get("status") == status]
        if min_confidence is not None:
            results = [f for f in results if f.get("confidence", 0) >= min_confidence]
        return results

    def count(self) -> int:
        return len(self.read_all())

    def mark_fixed(self, finding_id: str, fix_ref: str = "") -> bool:
        """Mark a finding as FIXED with cross-process file locking.

        This performs a read-modify-write cycle on findings.jsonl
        with atomic write (tempfile + os.replace).

        Returns True if finding was found and updated, False otherwise.
        """
        with self._lock:
            return self._mark_fixed_locked(finding_id, fix_ref)

    def _mark_fixed_locked(self, finding_id: str, fix_ref: str) -> bool:
        if not self._findings_path.exists():
            return False

        lines = self._findings_path.read_text(encoding="utf-8").splitlines()
        updated = False
        new_lines: list[str] = []

        now = datetime.now(timezone.utc).isoformat()

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                new_lines.append(line)
                continue

            if data.get("id") == finding_id:
                data["status"] = "fixed"
                data["updated_at"] = now
                if fix_ref:
                    comments = data.get("comments", [])
                    comments.append({
                        "expert_role": "_system",
                        "content": f"Marked as FIXED by FixSwarm. Ref: {fix_ref}",
                        "created_at": now,
                    })
                    data["comments"] = comments
                updated = True

            new_lines.append(json.dumps(data))

        if updated:
            self._atomic_write(new_lines)
            _log.info("Finding %s marked as fixed in %s", finding_id, self._findings_path)

        return updated

    def _atomic_write(self, lines: list[str]) -> None:
        """Atomic write via tempfile + os.replace."""
        self._findings_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self._findings_path.parent), suffix=".tmp"
        )
        try:
            fh = os.fdopen(tmp_fd, "w", encoding="utf-8")
        except Exception:
            os.close(tmp_fd)
            os.unlink(tmp_path)
            raise
        try:
            with fh:
                for line in lines:
                    fh.write(line + "\n")
            os.replace(tmp_path, str(self._findings_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def get_finding_reader(session_id: str, config: SuiteConfig | None = None) -> FindingReader:
    """Get a FindingReader for a review session by ID."""
    if config is None:
        config = SuiteConfig.load()
    session_dir = config.tool_sessions_path("review") / session_id
    return FindingReader(session_dir)


def search_all_findings(
    config: SuiteConfig,
    *,
    file: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    min_confidence: float | None = None,
) -> list[dict]:
    """Search findings across ALL review sessions."""
    sessions_dir = config.tool_sessions_path("review")
    if not sessions_dir.exists():
        return []

    results: list[dict] = []
    for entry in sorted(sessions_dir.iterdir()):
        if not entry.is_dir():
            continue
        reader = FindingReader(entry)
        if not reader.exists():
            continue
        findings = reader.search(
            file=file, severity=severity,
            status=status, min_confidence=min_confidence,
        )
        for f in findings:
            f["_session_id"] = entry.name
        results.extend(findings)

    return results
