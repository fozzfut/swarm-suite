"""Planner-Generator-Evaluator session -- generate-verify-retry loop artifact.

Today fix-swarm's `propose_fix` is one-shot: a generator proposes a
patch, it gets reviewed, applied or rejected. There is no built-in
retry path that uses an evaluator's structured feedback to refine the
candidate.

This module formalises the generate-verify-retry loop as a persistent
artifact so any tool (fix-swarm, doc-swarm, spec-swarm) can:

  1. Open a `PgveSession` for one task (`planner` writes the spec).
  2. Submit a `Candidate` (`generator` writes a proposal).
  3. Score it with an `Evaluation` (`evaluator` writes verdict + feedback).
  4. If verdict != accepted and retry budget remains: submit another
     candidate informed by the previous evaluation's feedback.
  5. When accepted (or budget exhausted), the session is finalised.

Each candidate carries its `previous_feedback` field so the generator
agent can read it directly instead of reaching back into JSONL. The
evaluator's verdict is one of `accepted` / `revise` / `rejected`. A
session retries while the verdict is `revise`; `rejected` means the
whole approach was wrong and the planner should produce a new spec.

Storage: `<kb_root>/pgve/<id>/pgve.json`, atomic write.

CONCURRENCY (READ THIS BEFORE TOUCHING):
Single-process ownership only. Same load+mutate+atomic_write pattern
as CompletionStore / VerificationStore. Two processes hitting the same
session race -- last write wins on the file, but updates can be lost.
Cross-process safety via a sibling .lock file is the planned remedy.
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
    MAX_CANDIDATES_HARD,
    MAX_TEXT_LEN,
    BoundedRecordCache,
    check_payload_size,
    check_text,
)

_log = logging.getLogger("swarm_kb.pgve")


PGVE_SCHEMA_VERSION = 1


VALID_VERDICTS: tuple[str, ...] = ("accepted", "revise", "rejected")

VALID_STATUSES: tuple[str, ...] = (
    "open", "accepted", "exhausted", "rejected", "cancelled",
)


# Default retry budgets. Tuned for fix-swarm: 5 candidates per task is
# enough room to incorporate evaluator feedback twice; more usually
# means the planner spec was wrong and you need a fresh start.
DEFAULT_MAX_CANDIDATES = 5


@dataclass
class Candidate:
    """One generator output for the task being worked on.

    `previous_feedback` quotes the evaluator's last `feedback` so the
    next generator pass has it in the payload directly (no JSONL
    re-read). Empty on the first candidate.
    """

    id: str = ""
    generator: str = ""
    content: str = ""
    payload: dict = field(default_factory=dict)
    previous_feedback: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "cand-" + secrets.token_hex(4)
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        check_text(self.content, "content")
        check_payload_size(self.payload, "payload")
        check_text(self.previous_feedback, "previous_feedback")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "generator": self.generator,
            "content": self.content,
            "payload": dict(self.payload),
            "previous_feedback": self.previous_feedback,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        return cls(
            id=d.get("id", ""),
            generator=d.get("generator", ""),
            content=d.get("content", ""),
            payload=dict(d.get("payload", {})),
            previous_feedback=d.get("previous_feedback", ""),
            created_at=d.get("created_at", ""),
        )


@dataclass
class Evaluation:
    """One evaluator's verdict on the most recent candidate.

    `verdict` drives the loop:
      * `accepted` -- session finalises with this candidate as winner.
      * `revise`   -- generator should produce a new candidate using
                      this evaluation's `feedback` as input.
      * `rejected` -- the whole approach is wrong; planner spec should
                      be rewritten before the loop continues.
    """

    id: str = ""
    candidate_id: str = ""
    evaluator: str = ""
    verdict: str = "revise"
    feedback: str = ""
    score: Optional[float] = None  # optional 0..1; rationale is load-bearing
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "eval-" + secrets.token_hex(4)
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.verdict not in VALID_VERDICTS:
            raise ValueError(
                f"verdict {self.verdict!r} not in {VALID_VERDICTS}"
            )
        check_text(self.feedback, "feedback")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "evaluator": self.evaluator,
            "verdict": self.verdict,
            "feedback": self.feedback,
            "score": self.score,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Evaluation":
        return cls(
            id=d.get("id", ""),
            candidate_id=d.get("candidate_id", ""),
            evaluator=d.get("evaluator", ""),
            verdict=d.get("verdict", "revise"),
            feedback=d.get("feedback", ""),
            score=d.get("score"),
            created_at=d.get("created_at", ""),
        )


@dataclass
class PgveSession:
    """One generate-verify-retry loop on one task spec."""

    id: str = ""
    task_spec: str = ""               # planner's description of what to produce
    candidates: list[Candidate] = field(default_factory=list)
    evaluations: list[Evaluation] = field(default_factory=list)
    accepted_candidate_id: str = ""    # set when an evaluation marks accepted
    status: str = "open"               # open|accepted|exhausted|rejected|cancelled
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    project_path: str = ""
    source_tool: str = ""
    source_session: str = ""
    schema_version: int = PGVE_SCHEMA_VERSION
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "pgve-" + secrets.token_hex(4)
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.task_spec:
            raise ValueError("task_spec must be non-empty")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be >= 1")
        if self.max_candidates > MAX_CANDIDATES_HARD:
            raise ValueError(
                f"max_candidates {self.max_candidates} exceeds hard cap {MAX_CANDIDATES_HARD}"
            )
        check_text(self.task_spec, "task_spec")

    # -- view ------------------------------------------------------------

    def latest_evaluation(self) -> Optional[Evaluation]:
        return self.evaluations[-1] if self.evaluations else None

    def latest_candidate(self) -> Optional[Candidate]:
        return self.candidates[-1] if self.candidates else None

    def remaining_budget(self) -> int:
        return max(0, self.max_candidates - len(self.candidates))

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "task_spec": self.task_spec,
            "candidates": [c.to_dict() for c in self.candidates],
            "evaluations": [e.to_dict() for e in self.evaluations],
            "accepted_candidate_id": self.accepted_candidate_id,
            "status": self.status,
            "max_candidates": self.max_candidates,
            "project_path": self.project_path,
            "source_tool": self.source_tool,
            "source_session": self.source_session,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PgveSession":
        # Per CLAUDE.md schema-versioning: unknown status -> "open" + warn.
        raw_status = d.get("status", "open")
        if raw_status not in VALID_STATUSES:
            _log.warning(
                "PgveSession %s: unknown status %r; falling back to 'open'",
                d.get("id", "?"), raw_status,
            )
            status = "open"
        else:
            status = raw_status
        v = int(d.get("schema_version", PGVE_SCHEMA_VERSION))
        if v > PGVE_SCHEMA_VERSION:
            _log.warning(
                "PgveSession %s schema_version %d > current %d; reading what we understand",
                d.get("id", "?"), v, PGVE_SCHEMA_VERSION,
            )
        return cls(
            schema_version=v,
            id=d.get("id", ""),
            task_spec=d.get("task_spec", ""),
            candidates=[Candidate.from_dict(c) for c in d.get("candidates", [])],
            evaluations=[Evaluation.from_dict(e) for e in d.get("evaluations", [])],
            accepted_candidate_id=d.get("accepted_candidate_id", ""),
            status=status,
            max_candidates=int(d.get("max_candidates", DEFAULT_MAX_CANDIDATES)),
            project_path=d.get("project_path", ""),
            source_tool=d.get("source_tool", ""),
            source_session=d.get("source_session", ""),
            created_at=d.get("created_at", ""),
        )


class PgveStore:
    """File-backed registry of PgveSession aggregates.

    Mirrors the JudgingEngine / VerificationStore pattern. Threading-
    safe within one process; multi-process callers carry the same
    cross-process race caveat as CompletionStore (see its docstring).
    """

    def __init__(
        self,
        root: Path,
        *,
        max_records: int = DEFAULT_MAX_RECORDS,
    ) -> None:
        self._root = Path(root)
        self._sessions: BoundedRecordCache[PgveSession] = BoundedRecordCache(max_records)
        self._lock = threading.RLock()
        self._load_all()

    # -- public API ------------------------------------------------------

    def start(
        self,
        *,
        task_spec: str,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        project_path: str = "",
        source_tool: str = "",
        source_session: str = "",
    ) -> PgveSession:
        s = PgveSession(
            task_spec=task_spec,
            max_candidates=max_candidates,
            project_path=project_path,
            source_tool=source_tool,
            source_session=source_session,
        )
        with self._lock:
            self._sessions.put(s.id, s)
            self._save(s.id)
        _log.info("Started pgve %s (budget=%d)", s.id, max_candidates)
        return s

    def submit_candidate(
        self,
        session_id: str,
        *,
        generator: str,
        content: str,
        payload: dict | None = None,
    ) -> Candidate:
        """Add a candidate; auto-fills `previous_feedback` from the latest evaluation."""
        with self._lock, cross_process_lock(self._lock_for(session_id)):
            s = self._force_reload(session_id)
            if s is None:
                raise ValueError(f"PgveSession {session_id!r} not found")
            if s.status != "open":
                raise ValueError(
                    f"PgveSession {session_id!r} is not open (status={s.status})"
                )
            if s.remaining_budget() <= 0:
                raise ValueError(
                    f"PgveSession {session_id!r} has no candidate budget left"
                )
            prev = s.latest_evaluation()
            cand = Candidate(
                generator=generator,
                content=content,
                payload=dict(payload or {}),
                previous_feedback=prev.feedback if prev else "",
            )
            s.candidates.append(cand)
            self._save(session_id)
        _log.info("Candidate %s submitted to %s by %s", cand.id, session_id, generator)
        # Return a copy to keep storage isolated from caller mutations.
        return Candidate.from_dict(cand.to_dict())

    def evaluate(
        self,
        session_id: str,
        *,
        evaluator: str,
        verdict: str,
        feedback: str,
        score: float | None = None,
    ) -> Evaluation:
        """Evaluate the LATEST candidate. Updates session status accordingly."""
        with self._lock, cross_process_lock(self._lock_for(session_id)):
            s = self._force_reload(session_id)
            if s is None:
                raise ValueError(f"PgveSession {session_id!r} not found")
            if s.status != "open":
                raise ValueError(
                    f"PgveSession {session_id!r} is not open (status={s.status})"
                )
            cand = s.latest_candidate()
            if cand is None:
                raise ValueError(
                    f"PgveSession {session_id!r} has no candidate to evaluate"
                )
            ev = Evaluation(
                candidate_id=cand.id,
                evaluator=evaluator,
                verdict=verdict,
                feedback=feedback,
                score=score,
            )
            s.evaluations.append(ev)
            if verdict == "accepted":
                s.accepted_candidate_id = cand.id
                s.status = "accepted"
            elif verdict == "rejected":
                s.status = "rejected"
            elif verdict == "revise" and s.remaining_budget() == 0:
                # Budget already spent; revise verdict means we can't try again.
                s.status = "exhausted"
            self._save(session_id)
        _log.info(
            "Evaluation %s on %s/%s -> %s (status=%s)",
            ev.id, session_id, cand.id, verdict, s.status,
        )
        return Evaluation.from_dict(ev.to_dict())

    def cancel(self, session_id: str) -> None:
        with self._lock, cross_process_lock(self._lock_for(session_id)):
            s = self._force_reload(session_id)
            if s is None:
                raise ValueError(f"PgveSession {session_id!r} not found")
            if s.status != "open":
                raise ValueError(
                    f"PgveSession {session_id!r} is not open (status={s.status})"
                )
            s.status = "cancelled"
            self._save(session_id)
        _log.info("Cancelled pgve %s", session_id)

    # -- cross-process lock helpers --------------------------------------

    def _lock_for(self, session_id: str) -> Path:
        return lock_path_for(self._root / session_id / "pgve.json")

    def _force_reload(self, session_id: str) -> Optional[PgveSession]:
        """Read the record straight from disk, bypassing the cache.

        MUST be called inside the cross-process lock for that record.
        """
        path = self._root / session_id / "pgve.json"
        if not path.exists():
            self._sessions.pop(session_id)
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            s = PgveSession.from_dict(data)
            self._sessions.put(s.id, s)
            return s
        except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
            _log.warning("Cannot reload pgve %s: %s", session_id, exc)
            return None

    def get(self, session_id: str) -> Optional[PgveSession]:
        with self._lock:
            s = self._get_or_load(session_id)
            return copy.deepcopy(s) if s else None

    def list_all(
        self,
        *,
        status: str = "",
        source_tool: str = "",
    ) -> list[PgveSession]:
        with self._lock:
            self._refresh_from_disk()
            results = list(self._sessions.values())
            if status:
                results = [s for s in results if s.status == status]
            if source_tool:
                results = [s for s in results if s.source_tool == source_tool]
            return [copy.deepcopy(s) for s in results]

    # -- internals -------------------------------------------------------

    def _get_or_load(self, session_id: str) -> Optional[PgveSession]:
        existing = self._sessions.get(session_id)
        if existing is not None:
            return existing
        path = self._root / session_id / "pgve.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            s = PgveSession.from_dict(data)
            self._sessions.put(s.id, s)
            return s
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _log.warning("Cannot load pgve %s: %s", session_id, exc)
            return None

    def _refresh_from_disk(self) -> None:
        if not self._root.exists():
            return
        for entry in self._root.iterdir():
            if not entry.is_dir() or entry.name in self._sessions:
                continue
            path = entry / "pgve.json"
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                s = PgveSession.from_dict(data)
                self._sessions.put(s.id, s)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                _log.warning("Skipping corrupt pgve in %s: %s", entry, exc)

    def _save(self, session_id: str) -> None:
        s = self._sessions.get(session_id)
        if s is None:
            return
        target = self._root / session_id / "pgve.json"
        atomic_write_text(target, json.dumps(s.to_dict(), indent=2, ensure_ascii=False))

    def _load_all(self) -> None:
        if not self._root.exists():
            return
        with self._lock:
            for entry in sorted(self._root.iterdir()):
                if not entry.is_dir():
                    continue
                path = entry / "pgve.json"
                if not path.exists():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    s = PgveSession.from_dict(data)
                    self._sessions.put(s.id, s)
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    _log.warning("Skipping corrupt pgve in %s: %s", entry, exc)
