"""Per-finding fix-attempt counter -- circuit breaker on the wrong-fix loop.

Tracks how many fix proposals have been APPLIED then later marked failed
(by regression check or by a re-review post-fix scan) for each finding.
After `MAX_ATTEMPTS_PER_FINDING` (default 3) the finding is escalated to
status `arch_review_needed` -- the systematic-debugging Iron Law:
    "3+ failures = architectural problem, not a fix problem"

The counter lives in `<session_dir>/fix_attempts.json` as a flat dict
{finding_id: int}. Single-writer per session via per-process lock + atomic
replace.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from swarm_core.io import atomic_write_text
from swarm_core.logging_setup import get_logger

_log = get_logger("kb.finding_attempts")

MAX_ATTEMPTS_PER_FINDING = 3
ESCALATED_STATUS = "arch_review_needed"


class FindingAttemptCounter:
    """Tracks fix attempts per finding within one session."""

    def __init__(self, session_dir: Path) -> None:
        self._dir = Path(session_dir)
        self._path = self._dir / "fix_attempts.json"
        self._lock = threading.Lock()

    def get(self, finding_id: str) -> int:
        return self._load().get(finding_id, 0)

    def increment(self, finding_id: str) -> int:
        """Increment the attempt counter; return new value."""
        with self._lock:
            data = self._load()
            data[finding_id] = data.get(finding_id, 0) + 1
            self._save(data)
            new = data[finding_id]
            if new >= MAX_ATTEMPTS_PER_FINDING:
                _log.warning(
                    "Finding %s reached %d fix attempts -- candidate for %s",
                    finding_id, new, ESCALATED_STATUS,
                )
            return new

    def should_escalate(self, finding_id: str) -> bool:
        """True if this finding has reached the architectural-review threshold."""
        return self.get(finding_id) >= MAX_ATTEMPTS_PER_FINDING

    def reset(self, finding_id: str) -> None:
        """Clear the counter (e.g. after operator reset for a deliberate retry)."""
        with self._lock:
            data = self._load()
            if finding_id in data:
                del data[finding_id]
                self._save(data)

    # ------------------------------------------------------------ internals

    def _load(self) -> dict[str, int]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            _log.warning("Corrupt fix_attempts.json at %s; resetting", self._path)
            return {}

    def _save(self, data: dict[str, int]) -> None:
        atomic_write_text(self._path, json.dumps(data, indent=2))
