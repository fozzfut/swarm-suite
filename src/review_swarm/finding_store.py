"""FindingStore -- Append-only JSONL storage with in-memory index for findings."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections import Counter
from pathlib import Path

from .logging_config import get_logger
from .models import Finding, Status, now_iso

_log = get_logger("finding_store")


class FindingStore:
    """Append-only JSONL storage with in-memory index for findings.

    Each finding is stored as one JSON line in the JSONL file.
    An in-memory dict provides fast lookup/filtering.
    """

    def __init__(self, jsonl_path: Path, max_findings: int = 10_000) -> None:
        self._path = Path(jsonl_path)
        self._max_findings = max_findings
        self._findings: dict[str, Finding] = {}
        self._lock = threading.Lock()
        self._load()

    # ── Public API ──────────────────────────────────────────────────────

    def post(self, finding: Finding) -> str:
        """Store a new finding. Sets timestamps, appends to JSONL.

        Returns the finding ID.
        Raises ValueError if the store has reached its max_findings limit.
        """
        with self._lock:
            if len(self._findings) >= self._max_findings:
                raise ValueError(
                    f"Finding limit reached ({self._max_findings}). "
                    "Cannot store more findings."
                )
            now = now_iso()
            finding.created_at = now
            finding.updated_at = now
            self._findings[finding.id] = finding
            self._append(finding)
            return finding.id

    def get(
        self,
        *,
        severity: str | None = None,
        category: str | None = None,
        status: str | None = None,
        file: str | None = None,
        expert_role: str | None = None,
        min_confidence: float | None = None,
        limit: int = 0,
        offset: int = 0,
    ) -> list[Finding]:
        """Return findings matching all provided filters.

        Filter values are strings compared against enum fields via ==.
        This works because all enums inherit from (str, Enum).

        Args:
            limit: Max results to return (0 = unlimited).
            offset: Number of results to skip before returning.
        """
        with self._lock:
            results = list(self._findings.values())

        if severity is not None:
            results = [f for f in results if f.severity == severity]
        if category is not None:
            results = [f for f in results if f.category == category]
        if status is not None:
            results = [f for f in results if f.status == status]
        if file is not None:
            results = [f for f in results if f.file == file]
        if expert_role is not None:
            results = [f for f in results if f.expert_role == expert_role]
        if min_confidence is not None:
            results = [f for f in results if f.confidence >= min_confidence]

        # Pagination
        if offset > 0:
            results = results[offset:]
        if limit > 0:
            results = results[:limit]

        return results

    def get_by_id(self, finding_id: str) -> Finding | None:
        """Return a finding by its ID, or None if not found."""
        with self._lock:
            return self._findings.get(finding_id)

    def count(self) -> int:
        """Return total number of findings."""
        with self._lock:
            return len(self._findings)

    def count_by_severity(self) -> dict[str, int]:
        """Return counts grouped by severity value."""
        with self._lock:
            counter: Counter[str] = Counter()
            for f in self._findings.values():
                counter[f.severity.value] += 1
            return dict(counter)

    def count_by_status(self) -> dict[str, int]:
        """Return counts grouped by status value."""
        with self._lock:
            counter: Counter[str] = Counter()
            for f in self._findings.values():
                counter[f.status.value] += 1
            return dict(counter)

    def find_duplicates(
        self,
        file: str,
        line_start: int,
        line_end: int,
        title: str,
        exclude_id: str = "",
    ) -> list[Finding]:
        """Find potential duplicate findings by overlapping location and similar title.

        Two findings are potential duplicates if they target the same file,
        have overlapping line ranges, and share title words.
        """
        with self._lock:
            candidates = []
            title_words = set(title.lower().split())
            for f in self._findings.values():
                if f.id == exclude_id:
                    continue
                if f.file != file:
                    continue
                # Check line overlap
                if f.line_start > line_end or f.line_end < line_start:
                    continue
                # Check title similarity (at least 50% word overlap)
                other_words = set(f.title.lower().split())
                if not title_words or not other_words:
                    continue
                overlap = len(title_words & other_words)
                union = len(title_words | other_words)
                if overlap / union >= 0.5:
                    candidates.append(f)
            return candidates

    # ── Mutation API (used by ReactionEngine) ───────────────────────────

    def update_status(self, finding_id: str, status: Status) -> None:
        """Update the status of a finding. Rewrites JSONL."""
        with self._lock:
            finding = self._findings.get(finding_id)
            if finding is None:
                raise KeyError(f"Finding {finding_id} not found")
            finding.status = status
            finding.updated_at = now_iso()
            self._flush()

    def add_reaction(self, finding_id: str, reaction_dict: dict) -> None:
        """Append a reaction dict to a finding's reactions list. Flushes."""
        with self._lock:
            finding = self._findings.get(finding_id)
            if finding is None:
                raise KeyError(f"Finding {finding_id} not found")
            finding.reactions.append(reaction_dict)
            finding.updated_at = now_iso()
            self._flush()

    def add_comment(self, finding_id: str, comment_dict: dict) -> None:
        """Append a comment dict to a finding's comments list. Flushes."""
        with self._lock:
            finding = self._findings.get(finding_id)
            if finding is None:
                raise KeyError(f"Finding {finding_id} not found")
            finding.comments.append(comment_dict)
            finding.updated_at = now_iso()
            self._flush()

    def add_related(self, finding_id: str, related_id: str) -> None:
        """Append a related finding ID if not already present. Flushes."""
        with self._lock:
            finding = self._findings.get(finding_id)
            if finding is None:
                raise KeyError(f"Finding {finding_id} not found")
            if related_id not in finding.related_findings:
                finding.related_findings.append(related_id)
                finding.updated_at = now_iso()
                self._flush()

    # ── I/O ─────────────────────────────────────────────────────────────

    def _flush(self) -> None:
        """Rewrite the entire JSONL file from in-memory state.

        Uses atomic write (write to temp file, then os.replace) to avoid
        data loss if two threads flush simultaneously.

        NOTE: _flush() rewrites the full file. This is O(N) per mutation but
        ensures atomicity via tempfile+replace. For v0.2, acceptable for <10K findings.

        NOTE: breaks strict append-only semantics for v0.1 -- acceptable
        because updates (status, reactions) require modifying existing lines.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self._path.parent), suffix=".tmp"
        )
        try:
            fh = os.fdopen(tmp_fd, "w", encoding="utf-8")
        except Exception:
            os.close(tmp_fd)
            os.unlink(tmp_path)
            raise
        try:
            with fh:
                for finding in self._findings.values():
                    fh.write(json.dumps(finding.to_dict()) + "\n")
            os.replace(tmp_path, str(self._path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _append(self, finding: Finding) -> None:
        """Append a single finding as one JSON line to the JSONL file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(finding.to_dict()) + "\n")

    def _load(self) -> None:
        """Load all findings from the JSONL file into memory."""
        if not self._path.exists():
            return
        with open(self._path, "r", encoding="utf-8") as fh:
            for line_num, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    finding = Finding.from_dict(data)
                    self._findings[finding.id] = finding
                except (json.JSONDecodeError, KeyError, ValueError) as exc:
                    _log.warning(
                        "Skipping corrupt line %d in %s: %s", line_num, self._path, exc
                    )
