"""CouncilAsAJudge -- multi-dimensional judging with rationales, not numbers.

A `Judging` is one subject (text, proposal, finding) evaluated by N
judges across N dimensions, where each judge owns exactly one dimension.
Each judge writes a `Judgment` carrying a verdict (`pass`/`fail`/`mixed`)
and a free-form rationale. The aggregator (the AI client, after all
dimensions are in) synthesises a single verdict + a structured table
of per-dimension rationales.

Distinct from `DebateEngine`: a debate is propose -> critique -> vote ->
winner; a judging is subject -> per-dimension verdicts -> synthesis.
The two compose: a debate can hand its winning proposal to a judging
("review the reviewer") before promoting to a decision.

Storage: `<judgings_root>/<judging_id>/judging.json` (atomic). One JSON
per judging, schema-versioned. Mirrors the DebateEngine pattern so
operators can grep, diff, and back up the same way.
"""

from __future__ import annotations

import copy
import json
import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from swarm_core.io import atomic_write_text

from ._filelock import cross_process_lock, lock_path_for
from ._limits import (
    DEFAULT_MAX_RECORDS,
    MAX_DIMENSIONS,
    MAX_SUGGESTED_CHANGES,
    MAX_TEXT_LEN,
    BoundedRecordCache,
    check_count,
    check_text,
)

_log = logging.getLogger("swarm_kb.judging")


JUDGING_SCHEMA_VERSION = 1


# Six default dimensions adapted from the swarms CouncilAsAJudge.
# Names are stable; the prompt for each dimension lives with the agent
# YAML, not here. New dimensions can be added by passing them at start.
DEFAULT_DIMENSIONS: tuple[str, ...] = (
    "accuracy",
    "helpfulness",
    "harmlessness",
    "coherence",
    "conciseness",
    "instruction_adherence",
)


VALID_VERDICTS: tuple[str, ...] = ("pass", "fail", "mixed", "abstain")

VALID_STATUSES: tuple[str, ...] = ("open", "resolved", "cancelled")

# Allowed values for `Judging.subject_kind`. "other" is the escape
# hatch for unmodelled cases; new categories should be added here
# rather than passed as ad-hoc strings.
VALID_SUBJECT_KINDS: tuple[str, ...] = (
    "text", "finding", "proposal", "adr", "fix", "other",
)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass
class Judgment:
    """One judge's verdict on one dimension.

    `verdict` is a string for forward-compat (clients may add new
    verdicts before we update this enum); `VALID_VERDICTS` documents the
    canonical set. `rationale` is the load-bearing field -- numbers are
    intentionally absent so consumers must read the reasoning.
    """

    id: str = ""
    judge: str = ""
    dimension: str = ""
    verdict: str = "abstain"
    rationale: str = ""
    suggested_changes: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "jdg-" + secrets.token_hex(4)
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.verdict not in VALID_VERDICTS:
            raise ValueError(
                f"verdict {self.verdict!r} not in {VALID_VERDICTS}"
            )
        check_text(self.rationale, "rationale")
        check_count(self.suggested_changes, "suggested_changes",
                    MAX_SUGGESTED_CHANGES)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "judge": self.judge,
            "dimension": self.dimension,
            "verdict": self.verdict,
            "rationale": self.rationale,
            "suggested_changes": list(self.suggested_changes),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Judgment":
        return cls(
            id=d.get("id", ""),
            judge=d.get("judge", ""),
            dimension=d.get("dimension", ""),
            verdict=d.get("verdict", "abstain"),
            rationale=d.get("rationale", ""),
            suggested_changes=list(d.get("suggested_changes", [])),
            created_at=d.get("created_at", ""),
        )


@dataclass
class JudgingSynthesis:
    """Aggregated verdict produced after every dimension is in.

    `overall` is one of `pass`/`fail`/`mixed` -- never numeric. The
    `dimensions` map preserves the per-dimension verdicts so consumers
    can drill down. `summary` is the load-bearing rationale.
    """

    overall: str = "mixed"
    summary: str = ""
    dimensions: dict[str, str] = field(default_factory=dict)
    follow_ups: list[str] = field(default_factory=list)
    synthesised_by: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.overall not in ("pass", "fail", "mixed"):
            raise ValueError(
                f"overall verdict {self.overall!r} not in pass/fail/mixed"
            )
        check_text(self.summary, "summary")

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "summary": self.summary,
            "dimensions": dict(self.dimensions),
            "follow_ups": list(self.follow_ups),
            "synthesised_by": self.synthesised_by,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "JudgingSynthesis":
        return cls(
            overall=d.get("overall", "mixed"),
            summary=d.get("summary", ""),
            dimensions=dict(d.get("dimensions", {})),
            follow_ups=list(d.get("follow_ups", [])),
            synthesised_by=d.get("synthesised_by", ""),
            created_at=d.get("created_at", ""),
        )


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


@dataclass
class Judging:
    """One subject evaluated across N dimensions by N judges."""

    id: str = ""
    subject: str = ""
    subject_kind: str = "text"          # text|finding|proposal|adr|other
    subject_ref: str = ""               # e.g. "f-a1b2", "adr-c3d4"
    dimensions: list[str] = field(
        default_factory=lambda: list(DEFAULT_DIMENSIONS),
    )
    judgments: list[Judgment] = field(default_factory=list)
    synthesis: Optional[JudgingSynthesis] = None
    status: str = "open"                # open|resolved|cancelled
    project_path: str = ""
    source_tool: str = ""
    source_session: str = ""
    schema_version: int = JUDGING_SCHEMA_VERSION
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "judg-" + secrets.token_hex(4)
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.dimensions:
            raise ValueError("a Judging must have at least one dimension")
        check_count(self.dimensions, "dimensions", MAX_DIMENSIONS)
        if self.subject_kind not in VALID_SUBJECT_KINDS:
            raise ValueError(
                f"subject_kind {self.subject_kind!r} not in {VALID_SUBJECT_KINDS}"
            )
        check_text(self.subject, "subject")

    # -- mutations ---------------------------------------------------------

    def add_judgment(self, j: Judgment) -> str:
        """Add a judgment. One judge per dimension; later submissions overwrite."""
        if j.dimension not in self.dimensions:
            raise ValueError(
                f"dimension {j.dimension!r} not in {self.dimensions}"
            )
        # Replace earlier judgment by the same judge on the same dimension.
        self.judgments = [
            old for old in self.judgments
            if not (old.judge == j.judge and old.dimension == j.dimension)
        ]
        self.judgments.append(j)
        return j.id

    def covered_dimensions(self) -> set[str]:
        return {j.dimension for j in self.judgments}

    def is_complete(self) -> bool:
        return self.covered_dimensions() == set(self.dimensions)

    def get_judgments_for(self, dimension: str) -> list[Judgment]:
        return [j for j in self.judgments if j.dimension == dimension]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "subject": self.subject,
            "subject_kind": self.subject_kind,
            "subject_ref": self.subject_ref,
            "dimensions": list(self.dimensions),
            "judgments": [j.to_dict() for j in self.judgments],
            "synthesis": self.synthesis.to_dict() if self.synthesis else None,
            "status": self.status,
            "project_path": self.project_path,
            "source_tool": self.source_tool,
            "source_session": self.source_session,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Judging":
        synth = d.get("synthesis")
        # Per CLAUDE.md schema-versioning: unknown status -> "open" + warn.
        raw_status = d.get("status", "open")
        if raw_status not in VALID_STATUSES:
            _log.warning(
                "Judging %s: unknown status %r; falling back to 'open'",
                d.get("id", "?"), raw_status,
            )
            status = "open"
        else:
            status = raw_status
        v = int(d.get("schema_version", JUDGING_SCHEMA_VERSION))
        if v > JUDGING_SCHEMA_VERSION:
            _log.warning(
                "Judging %s schema_version %d > current %d; reading what we understand",
                d.get("id", "?"), v, JUDGING_SCHEMA_VERSION,
            )
        return cls(
            schema_version=v,
            id=d.get("id", ""),
            subject=d.get("subject", ""),
            subject_kind=d.get("subject_kind", "text"),
            subject_ref=d.get("subject_ref", ""),
            dimensions=list(d.get("dimensions", DEFAULT_DIMENSIONS)),
            judgments=[Judgment.from_dict(j) for j in d.get("judgments", [])],
            synthesis=JudgingSynthesis.from_dict(synth) if synth else None,
            status=status,
            project_path=d.get("project_path", ""),
            source_tool=d.get("source_tool", ""),
            source_session=d.get("source_session", ""),
            created_at=d.get("created_at", ""),
        )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class JudgingEngine:
    """File-backed registry of `Judging` aggregates.

    Mirrors `DebateEngine` shape but without proposals/votes -- a
    judging is single-subject and verdict-only. Atomic writes via
    `atomic_write_text`.
    """

    def __init__(
        self,
        judgings_dir: Path,
        *,
        max_records: int = DEFAULT_MAX_RECORDS,
    ) -> None:
        self._dir = Path(judgings_dir)
        # In-memory cache bounded to avoid unbounded RAM growth on long
        # uptimes. Disk records persist; old records are reloaded on
        # demand via _get_or_load when accessed.
        self._judgings: BoundedRecordCache[Judging] = BoundedRecordCache(max_records)
        self._lock = threading.RLock()
        self._load_all()

    # -- public API --------------------------------------------------------

    def start(
        self,
        subject: str,
        *,
        dimensions: list[str] | None = None,
        subject_kind: str = "text",
        subject_ref: str = "",
        project_path: str = "",
        source_tool: str = "",
        source_session: str = "",
    ) -> Judging:
        if not subject:
            raise ValueError("subject must be non-empty")
        dims = list(dimensions) if dimensions else list(DEFAULT_DIMENSIONS)
        judging = Judging(
            subject=subject,
            subject_kind=subject_kind,
            subject_ref=subject_ref,
            dimensions=dims,
            project_path=project_path,
            source_tool=source_tool,
            source_session=source_session,
        )
        with self._lock:
            self._judgings.put(judging.id, judging)
            self._save(judging.id)
        _log.info("Started judging %s on %s", judging.id, subject_kind)
        return judging

    def judge(
        self,
        judging_id: str,
        *,
        judge: str,
        dimension: str,
        verdict: str,
        rationale: str,
        suggested_changes: list[str] | None = None,
    ) -> str:
        with self._lock, cross_process_lock(self._lock_for(judging_id)):
            # Always force-reload from disk inside the cross-process
            # lock so we observe writes from any sibling process before
            # mutating. Cache is updated as a side-effect.
            j = self._force_reload(judging_id)
            if j is None:
                raise ValueError(f"Judging {judging_id!r} not found")
            if j.status != "open":
                raise ValueError(
                    f"Judging {judging_id!r} is not open (status={j.status})"
                )
            jm = Judgment(
                judge=judge,
                dimension=dimension,
                verdict=verdict,
                rationale=rationale,
                suggested_changes=list(suggested_changes or []),
            )
            jid = j.add_judgment(jm)
            self._save(judging_id)
        _log.info("Judgment %s on %s/%s by %s", jid, judging_id, dimension, judge)
        return jid

    def synthesise(
        self,
        judging_id: str,
        *,
        overall: str,
        summary: str,
        dimensions: dict[str, str] | None = None,
        follow_ups: list[str] | None = None,
        synthesised_by: str = "",
    ) -> JudgingSynthesis:
        with self._lock, cross_process_lock(self._lock_for(judging_id)):
            j = self._force_reload(judging_id)
            if j is None:
                raise ValueError(f"Judging {judging_id!r} not found")
            if j.status != "open":
                raise ValueError(
                    f"Judging {judging_id!r} is not open (status={j.status})"
                )
            # If caller didn't provide per-dimension verdicts, derive from judgments.
            dims = dict(dimensions) if dimensions else self._derive_dimensions(j)
            synth = JudgingSynthesis(
                overall=overall,
                summary=summary,
                dimensions=dims,
                follow_ups=list(follow_ups or []),
                synthesised_by=synthesised_by,
            )
            j.synthesis = synth
            j.status = "resolved"
            self._save(judging_id)
        _log.info("Synthesised judging %s -> %s", judging_id, overall)
        return synth

    def cancel(self, judging_id: str) -> None:
        with self._lock, cross_process_lock(self._lock_for(judging_id)):
            j = self._force_reload(judging_id)
            if j is None:
                raise ValueError(f"Judging {judging_id!r} not found")
            if j.status != "open":
                raise ValueError(
                    f"Judging {judging_id!r} is not open (status={j.status})"
                )
            j.status = "cancelled"
            self._save(judging_id)
        _log.info("Cancelled judging %s", judging_id)

    # -- cross-process lock helpers --------------------------------------

    def _lock_for(self, judging_id: str) -> Path:
        return lock_path_for(self._dir / judging_id / "judging.json")

    def _force_reload(self, judging_id: str) -> Optional[Judging]:
        """Read the record straight from disk, bypassing the cache.

        MUST be called inside the cross-process lock for that record.
        Updates the in-memory cache as a side-effect so subsequent
        reads see the latest state without a re-load.
        """
        path = self._dir / judging_id / "judging.json"
        if not path.exists():
            self._judgings.pop(judging_id)
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            j = Judging.from_dict(data)
            self._judgings.put(j.id, j)
            return j
        except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
            _log.warning("Cannot reload judging %s: %s", judging_id, exc)
            return None

    def get(self, judging_id: str) -> Optional[Judging]:
        with self._lock:
            j = self._get_or_load(judging_id)
            return copy.deepcopy(j) if j else None

    def list_all(
        self,
        *,
        status: str = "",
        source_tool: str = "",
    ) -> list[Judging]:
        with self._lock:
            self._refresh_from_disk()
            results = list(self._judgings.values())
            if status:
                results = [j for j in results if j.status == status]
            if source_tool:
                results = [j for j in results if j.source_tool == source_tool]
            return [copy.deepcopy(j) for j in results]

    def count(self, status: str = "") -> int:
        with self._lock:
            self._refresh_from_disk()
            if not status:
                return len(self._judgings)
            return sum(1 for j in self._judgings.values() if j.status == status)

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _derive_dimensions(j: Judging) -> dict[str, str]:
        """For each declared dimension, pick the latest judge's verdict.

        If a dimension has no judgments, use 'abstain'.
        """
        dims: dict[str, str] = {}
        for d in j.dimensions:
            judgments = j.get_judgments_for(d)
            dims[d] = judgments[-1].verdict if judgments else "abstain"
        return dims

    def _get_or_load(self, judging_id: str) -> Optional[Judging]:
        existing = self._judgings.get(judging_id)
        if existing is not None:
            return existing
        path = self._dir / judging_id / "judging.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            j = Judging.from_dict(data)
            self._judgings.put(j.id, j)
            return j
        except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
            _log.warning("Cannot load judging %s: %s", judging_id, exc)
            return None

    def _refresh_from_disk(self) -> None:
        if not self._dir.exists():
            return
        for entry in self._dir.iterdir():
            if not entry.is_dir() or entry.name in self._judgings:
                continue
            path = entry / "judging.json"
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                j = Judging.from_dict(data)
                self._judgings.put(j.id, j)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                _log.warning("Skipping corrupt judging in %s: %s", entry, exc)

    def _save(self, judging_id: str) -> None:
        j = self._judgings.get(judging_id)
        if j is None:
            return
        target = self._dir / judging_id / "judging.json"
        atomic_write_text(target, json.dumps(j.to_dict(), indent=2, ensure_ascii=False))

    def _load_all(self) -> None:
        if not self._dir.exists():
            return
        with self._lock:
            for entry in sorted(self._dir.iterdir()):
                if not entry.is_dir():
                    continue
                path = entry / "judging.json"
                if not path.exists():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    j = Judging.from_dict(data)
                    self._judgings.put(j.id, j)
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    _log.warning("Skipping corrupt judging in %s: %s", entry, exc)
