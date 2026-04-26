"""VerificationReport -- formalises the verify-stage artifact.

The pipeline's `verify` stage already runs check_regression and the
quality gate, but their outputs lived only in tool-specific session
JSONL streams. There was no single artifact that said "fix session F
was verified, here is the evidence, here is the verdict" -- so the
gate to advance into `doc` was opaque.

This module gives that gate a body: a `VerificationReport` aggregates
evidence (test diff, regression scan, quality-gate result, optional
CouncilAsAJudge judgings) and ends with a structured `verdict` (pass /
fail / partial) plus a load-bearing rationale. doc-swarm and the
pipeline gate read the verdict; humans read the rationale.

Storage: `<kb_root>/verifications/<id>/verification.json`, atomic
write. One file per report, schema-versioned.

The store is intentionally thin -- it does not RUN tests or quality
gates. The fix-swarm tooling supplies evidence via add_evidence(); the
synthesis is a separate explicit call so the orchestrator can decide
when "enough evidence" has accumulated.

CONCURRENCY (READ THIS BEFORE TOUCHING):
Same model as CompletionStore. Single-process ownership is assumed:
load+mutate+atomic_write_text under the per-process threading.RLock.
Two processes hitting the same report would race -- last-write-wins on
the file, but logical updates can be lost. Cross-process safety is the
planned remedy via portalocker on a sibling .lock; absent today.
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
    MAX_BLOCKING_ISSUES,
    MAX_EVIDENCE_PER_REPORT,
    MAX_FOLLOW_UPS,
    MAX_PAYLOAD_BYTES,
    MAX_TEXT_LEN,
    BoundedRecordCache,
    check_count,
    check_payload_size,
    check_text,
)

_log = logging.getLogger("swarm_kb.verification")


VERIFICATION_SCHEMA_VERSION = 1


# Allowed evidence kinds. New kinds may be added; consumers that don't
# recognise a kind should ignore it (CLAUDE.md schema-versioning rule).
VALID_EVIDENCE_KINDS: tuple[str, ...] = (
    "test_diff",        # before/after test count snapshot
    "regression_scan",  # output of check_regression
    "quality_gate",     # kb_check_quality_gate result
    "judging",          # references a CouncilAsAJudge judging_id
    "manual_note",      # operator-supplied free text
)

VALID_VERDICTS: tuple[str, ...] = ("pass", "fail", "partial")

VALID_STATUSES: tuple[str, ...] = ("open", "finalised", "cancelled")


@dataclass
class VerificationEvidence:
    """One piece of evidence attached to a verification report.

    `data` shape varies by `kind`. The store does not validate inner
    structure -- consumers (doc-swarm gate, the AI synthesising the
    verdict) read what they expect and ignore what they don't.
    """

    id: str = ""
    kind: str = ""
    summary: str = ""
    data: dict = field(default_factory=dict)
    source_tool: str = ""
    source_session: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "ev-" + secrets.token_hex(4)
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.kind not in VALID_EVIDENCE_KINDS:
            raise ValueError(
                f"evidence kind {self.kind!r} not in {VALID_EVIDENCE_KINDS}"
            )
        check_text(self.summary, "summary")
        check_payload_size(self.data, "data")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "summary": self.summary,
            "data": dict(self.data),
            "source_tool": self.source_tool,
            "source_session": self.source_session,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VerificationEvidence":
        return cls(
            id=d.get("id", ""),
            kind=d.get("kind", ""),
            summary=d.get("summary", ""),
            data=dict(d.get("data", {})),
            source_tool=d.get("source_tool", ""),
            source_session=d.get("source_session", ""),
            created_at=d.get("created_at", ""),
        )


@dataclass
class VerificationVerdict:
    """The aggregator's synthesis after every evidence piece is in."""

    overall: str = "partial"
    summary: str = ""
    blocking_issues: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    synthesised_by: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.overall not in VALID_VERDICTS:
            raise ValueError(
                f"overall verdict {self.overall!r} not in {VALID_VERDICTS}"
            )
        check_text(self.summary, "summary")
        check_count(self.blocking_issues, "blocking_issues", MAX_BLOCKING_ISSUES)
        check_count(self.follow_ups, "follow_ups", MAX_FOLLOW_UPS)

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "summary": self.summary,
            "blocking_issues": list(self.blocking_issues),
            "follow_ups": list(self.follow_ups),
            "synthesised_by": self.synthesised_by,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VerificationVerdict":
        return cls(
            overall=d.get("overall", "partial"),
            summary=d.get("summary", ""),
            blocking_issues=list(d.get("blocking_issues", [])),
            follow_ups=list(d.get("follow_ups", [])),
            synthesised_by=d.get("synthesised_by", ""),
            created_at=d.get("created_at", ""),
        )


@dataclass
class VerificationReport:
    """Aggregates evidence + verdict for one fix-cycle's verification."""

    id: str = ""
    fix_session: str = ""        # the fix session being verified
    review_session: str = ""     # optional source review session
    project_path: str = ""
    evidence: list[VerificationEvidence] = field(default_factory=list)
    verdict: Optional[VerificationVerdict] = None
    status: str = "open"         # open|finalised|cancelled
    schema_version: int = VERIFICATION_SCHEMA_VERSION
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "verify-" + secrets.token_hex(4)
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def add_evidence(self, ev: VerificationEvidence) -> str:
        if len(self.evidence) >= MAX_EVIDENCE_PER_REPORT:
            raise ValueError(
                f"evidence count would exceed limit {MAX_EVIDENCE_PER_REPORT}"
            )
        self.evidence.append(ev)
        return ev.id

    def evidence_by_kind(self, kind: str) -> list[VerificationEvidence]:
        return [e for e in self.evidence if e.kind == kind]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "fix_session": self.fix_session,
            "review_session": self.review_session,
            "project_path": self.project_path,
            "evidence": [e.to_dict() for e in self.evidence],
            "verdict": self.verdict.to_dict() if self.verdict else None,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VerificationReport":
        verdict_raw = d.get("verdict")
        # Per CLAUDE.md schema-versioning: tolerate unknown status values
        # by falling back to "open" so downstream filters keep working.
        raw_status = d.get("status", "open")
        if raw_status not in VALID_STATUSES:
            _log.warning(
                "VerificationReport %s: unknown status %r; falling back to 'open'",
                d.get("id", "?"), raw_status,
            )
            status = "open"
        else:
            status = raw_status
        v = int(d.get("schema_version", VERIFICATION_SCHEMA_VERSION))
        if v > VERIFICATION_SCHEMA_VERSION:
            _log.warning(
                "VerificationReport %s schema_version %d > current %d; reading what we understand",
                d.get("id", "?"), v, VERIFICATION_SCHEMA_VERSION,
            )
        return cls(
            schema_version=v,
            id=d.get("id", ""),
            fix_session=d.get("fix_session", ""),
            review_session=d.get("review_session", ""),
            project_path=d.get("project_path", ""),
            evidence=[
                VerificationEvidence.from_dict(e) for e in d.get("evidence", [])
            ],
            verdict=VerificationVerdict.from_dict(verdict_raw) if verdict_raw else None,
            status=status,
            created_at=d.get("created_at", ""),
        )


class VerificationStore:
    """File-backed registry of verification reports.

    Mirrors the JudgingEngine pattern: per-id directory with a single
    `verification.json`. Atomic writes via swarm_core.io.atomic_write_text.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_records: int = DEFAULT_MAX_RECORDS,
    ) -> None:
        self._root = Path(root)
        # Bounded LRU; on-disk records persist independently.
        self._reports: BoundedRecordCache[VerificationReport] = BoundedRecordCache(max_records)
        self._lock = threading.RLock()
        self._load_all()

    # -- public API ------------------------------------------------------

    def start(
        self,
        *,
        fix_session: str,
        review_session: str = "",
        project_path: str = "",
    ) -> VerificationReport:
        if not fix_session:
            raise ValueError("fix_session must be non-empty")
        report = VerificationReport(
            fix_session=fix_session,
            review_session=review_session,
            project_path=project_path,
        )
        with self._lock:
            self._reports.put(report.id, report)
            self._save(report.id)
        _log.info("Started verification %s for fix=%s", report.id, fix_session)
        return report

    def add_evidence(
        self,
        report_id: str,
        *,
        kind: str,
        summary: str,
        data: dict | None = None,
        source_tool: str = "",
        source_session: str = "",
    ) -> str:
        with self._lock, cross_process_lock(self._lock_for(report_id)):
            r = self._force_reload(report_id)
            if r is None:
                raise ValueError(f"Verification {report_id!r} not found")
            if r.status != "open":
                raise ValueError(
                    f"Verification {report_id!r} is not open (status={r.status})"
                )
            ev = VerificationEvidence(
                kind=kind,
                summary=summary,
                data=dict(data or {}),
                source_tool=source_tool,
                source_session=source_session,
            )
            ev_id = r.add_evidence(ev)
            self._save(report_id)
        _log.info("Evidence %s (%s) added to %s", ev_id, kind, report_id)
        return ev_id

    def finalise(
        self,
        report_id: str,
        *,
        overall: str,
        summary: str,
        blocking_issues: list[str] | None = None,
        follow_ups: list[str] | None = None,
        synthesised_by: str = "",
    ) -> VerificationVerdict:
        with self._lock, cross_process_lock(self._lock_for(report_id)):
            r = self._force_reload(report_id)
            if r is None:
                raise ValueError(f"Verification {report_id!r} not found")
            if r.status != "open":
                raise ValueError(
                    f"Verification {report_id!r} is not open (status={r.status})"
                )
            verdict = VerificationVerdict(
                overall=overall,
                summary=summary,
                blocking_issues=list(blocking_issues or []),
                follow_ups=list(follow_ups or []),
                synthesised_by=synthesised_by,
            )
            r.verdict = verdict
            r.status = "finalised"
            self._save(report_id)
        _log.info("Finalised verification %s -> %s", report_id, overall)
        return verdict

    def cancel(self, report_id: str) -> None:
        with self._lock, cross_process_lock(self._lock_for(report_id)):
            r = self._force_reload(report_id)
            if r is None:
                raise ValueError(f"Verification {report_id!r} not found")
            if r.status != "open":
                raise ValueError(
                    f"Verification {report_id!r} is not open (status={r.status})"
                )
            r.status = "cancelled"
            self._save(report_id)
        _log.info("Cancelled verification %s", report_id)

    # -- cross-process lock helpers --------------------------------------

    def _lock_for(self, report_id: str) -> Path:
        return lock_path_for(self._root / report_id / "verification.json")

    def _force_reload(self, report_id: str) -> Optional[VerificationReport]:
        """Read the record straight from disk, bypassing the cache.

        MUST be called inside the cross-process lock for that record.
        """
        path = self._root / report_id / "verification.json"
        if not path.exists():
            self._reports.pop(report_id)
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            r = VerificationReport.from_dict(data)
            self._reports.put(r.id, r)
            return r
        except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
            _log.warning("Cannot reload verification %s: %s", report_id, exc)
            return None

    def get(self, report_id: str) -> Optional[VerificationReport]:
        with self._lock:
            r = self._get_or_load(report_id)
            return copy.deepcopy(r) if r else None

    def list_all(
        self,
        *,
        status: str = "",
        fix_session: str = "",
    ) -> list[VerificationReport]:
        with self._lock:
            self._refresh_from_disk()
            results = list(self._reports.values())
            if status:
                results = [r for r in results if r.status == status]
            if fix_session:
                results = [r for r in results if r.fix_session == fix_session]
            return [copy.deepcopy(r) for r in results]

    # -- internals -------------------------------------------------------

    def _get_or_load(self, report_id: str) -> Optional[VerificationReport]:
        existing = self._reports.get(report_id)
        if existing is not None:
            return existing
        path = self._root / report_id / "verification.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            r = VerificationReport.from_dict(data)
            self._reports.put(r.id, r)
            return r
        except (OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
            _log.warning("Cannot load verification %s: %s", report_id, exc)
            return None

    def _refresh_from_disk(self) -> None:
        if not self._root.exists():
            return
        for entry in self._root.iterdir():
            if not entry.is_dir() or entry.name in self._reports:
                continue
            path = entry / "verification.json"
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                r = VerificationReport.from_dict(data)
                self._reports.put(r.id, r)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                _log.warning("Skipping corrupt verification in %s: %s", entry, exc)

    def _save(self, report_id: str) -> None:
        r = self._reports.get(report_id)
        if r is None:
            return
        target = self._root / report_id / "verification.json"
        atomic_write_text(target, json.dumps(r.to_dict(), indent=2, ensure_ascii=False))

    def _load_all(self) -> None:
        if not self._root.exists():
            return
        with self._lock:
            for entry in sorted(self._root.iterdir()):
                if not entry.is_dir():
                    continue
                path = entry / "verification.json"
                if not path.exists():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    r = VerificationReport.from_dict(data)
                    self._reports.put(r.id, r)
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    _log.warning("Skipping corrupt verification in %s: %s", entry, exc)
