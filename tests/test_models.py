"""Tests for review_swarm.models -- Finding, Claim, Reaction dataclasses and enums."""

import re
from datetime import datetime, timedelta, timezone

import pytest

from review_swarm.models import (
    Action,
    Category,
    Claim,
    ClaimStatus,
    Finding,
    Reaction,
    ReactionType,
    Severity,
    Status,
)


# ── Enum tests ──────────────────────────────────────────────────────────


class TestSeverity:
    def test_string_values(self):
        assert Severity.CRITICAL == "critical"
        assert Severity.HIGH == "high"
        assert Severity.MEDIUM == "medium"
        assert Severity.LOW == "low"
        assert Severity.INFO == "info"

    def test_member_count(self):
        assert len(Severity) == 5

    def test_from_string(self):
        assert Severity("critical") is Severity.CRITICAL


class TestCategory:
    def test_string_values(self):
        assert Category.BUG == "bug"
        assert Category.OMISSION == "omission"
        assert Category.INCONSISTENCY == "inconsistency"
        assert Category.SECURITY == "security"
        assert Category.PERFORMANCE == "performance"
        assert Category.STYLE == "style"
        assert Category.DESIGN == "design"

    def test_member_count(self):
        assert len(Category) == 7


class TestAction:
    def test_string_values(self):
        assert Action.FIX == "fix"
        assert Action.INVESTIGATE == "investigate"
        assert Action.DOCUMENT == "document"
        assert Action.IGNORE == "ignore"

    def test_member_count(self):
        assert len(Action) == 4


class TestStatus:
    def test_string_values(self):
        assert Status.OPEN == "open"
        assert Status.CONFIRMED == "confirmed"
        assert Status.DISPUTED == "disputed"
        assert Status.FIXED == "fixed"
        assert Status.WONTFIX == "wontfix"
        assert Status.DUPLICATE == "duplicate"

    def test_member_count(self):
        assert len(Status) == 6


class TestClaimStatus:
    def test_string_values(self):
        assert ClaimStatus.ACTIVE == "active"
        assert ClaimStatus.RELEASED == "released"
        assert ClaimStatus.EXPIRED == "expired"

    def test_member_count(self):
        assert len(ClaimStatus) == 3

    def test_from_string(self):
        assert ClaimStatus("active") is ClaimStatus.ACTIVE
        assert ClaimStatus("released") is ClaimStatus.RELEASED
        assert ClaimStatus("expired") is ClaimStatus.EXPIRED


class TestReactionType:
    def test_string_values(self):
        assert ReactionType.CONFIRM == "confirm"
        assert ReactionType.DISPUTE == "dispute"
        assert ReactionType.EXTEND == "extend"
        assert ReactionType.DUPLICATE == "duplicate"

    def test_member_count(self):
        assert len(ReactionType) == 4


# ── Finding tests ───────────────────────────────────────────────────────


class TestFinding:
    def _make_finding(self, **overrides):
        defaults = dict(
            id="f-abc123",
            session_id="sess-001",
            expert_role="concurrency",
            agent_id="agent-1",
            file="src/main.py",
            line_start=10,
            line_end=20,
            title="Race condition in handler",
            snippet="x = shared_state",
            severity=Severity.HIGH,
            category=Category.BUG,
        )
        defaults.update(overrides)
        return Finding(**defaults)

    def test_create_with_all_fields(self):
        f = self._make_finding()
        assert f.id == "f-abc123"
        assert f.session_id == "sess-001"
        assert f.expert_role == "concurrency"
        assert f.agent_id == "agent-1"
        assert f.file == "src/main.py"
        assert f.line_start == 10
        assert f.line_end == 20
        assert f.title == "Race condition in handler"
        assert f.snippet == "x = shared_state"
        assert f.severity == Severity.HIGH
        assert f.category == Category.BUG

    def test_defaults(self):
        f = Finding(
            id="f-000000",
            session_id="s",
            expert_role="r",
            agent_id="a",
            file="f.py",
            line_start=1,
            line_end=1,
        )
        assert f.snippet == ""
        assert f.severity == Severity.MEDIUM
        assert f.category == Category.BUG
        assert f.title == ""
        assert f.actual == ""
        assert f.expected == ""
        assert f.source_ref == ""
        assert f.suggestion_action == Action.INVESTIGATE
        assert f.suggestion_detail == ""
        assert f.confidence == 0.5
        assert f.tags == []
        assert f.related_findings == []
        assert f.status == Status.OPEN
        assert f.reactions == []
        assert f.created_at == ""
        assert f.updated_at == ""

    def test_generate_id_format(self):
        fid = Finding.generate_id()
        # "f-" prefix + 6 hex chars = 8 chars total
        assert len(fid) == 8
        assert fid.startswith("f-")
        assert re.match(r"^f-[0-9a-f]{6}$", fid)

    def test_generate_id_uniqueness(self):
        ids = {Finding.generate_id() for _ in range(100)}
        # With 6 hex chars (16M possibilities), 100 samples should be unique
        assert len(ids) == 100

    def test_to_dict(self):
        f = self._make_finding()
        d = f.to_dict()
        assert isinstance(d, dict)
        assert d["id"] == "f-abc123"
        assert d["severity"] == "high"
        assert d["category"] == "bug"
        assert d["status"] == "open"
        assert d["suggestion_action"] == "investigate"
        assert d["line_start"] == 10
        assert d["confidence"] == 0.5
        assert d["tags"] == []

    def test_from_dict(self):
        f = self._make_finding(tags=["thread-safety"], confidence=0.9)
        d = f.to_dict()
        f2 = Finding.from_dict(d)
        assert f2.id == f.id
        assert f2.severity == f.severity
        assert f2.category == f.category
        assert f2.status == f.status
        assert f2.suggestion_action == f.suggestion_action
        assert f2.tags == ["thread-safety"]
        assert f2.confidence == 0.9

    def test_roundtrip(self):
        f = self._make_finding(
            tags=["race", "lock"],
            related_findings=["f-other1"],
            confidence=0.8,
            actual="No lock held",
            expected="Lock should be held",
            source_ref="docs/threading.md",
            suggestion_action=Action.FIX,
            suggestion_detail="Add threading.Lock",
        )
        d = f.to_dict()
        f2 = Finding.from_dict(d)
        assert f2.to_dict() == d


# ── Claim tests ─────────────────────────────────────────────────────────


class TestClaim:
    def _make_claim(self, **overrides):
        defaults = dict(
            id="c-abc123",
            session_id="sess-001",
            file="src/main.py",
            expert_role="concurrency",
            agent_id="agent-1",
            claimed_at=datetime.now(timezone.utc).isoformat(),
        )
        defaults.update(overrides)
        return Claim(**defaults)

    def test_create_with_defaults(self):
        c = self._make_claim()
        assert c.ttl_seconds == 1800
        assert c.status == ClaimStatus.ACTIVE

    def test_is_expired_fresh(self):
        c = self._make_claim()
        assert not c.is_expired()

    def test_is_expired_old(self):
        old_time = (datetime.now(timezone.utc) - timedelta(seconds=3600)).isoformat()
        c = self._make_claim(claimed_at=old_time, ttl_seconds=1800)
        assert c.is_expired()

    def test_is_expired_boundary(self):
        """Claim with ttl=0 should be expired immediately (or nearly so)."""
        c = self._make_claim(ttl_seconds=0)
        # Allow tiny tolerance -- the claim was just created, but ttl=0
        # means it expires at claimed_at, so it should be expired
        assert c.is_expired()

    def test_generate_id_format(self):
        cid = Claim.generate_id()
        assert len(cid) == 8
        assert cid.startswith("c-")
        assert re.match(r"^c-[0-9a-f]{6}$", cid)

    def test_to_dict(self):
        c = self._make_claim()
        d = c.to_dict()
        assert isinstance(d, dict)
        assert d["id"] == "c-abc123"
        assert d["ttl_seconds"] == 1800
        assert d["status"] == "active"

    def test_from_dict(self):
        c = self._make_claim(ttl_seconds=900, status=ClaimStatus.RELEASED)
        d = c.to_dict()
        c2 = Claim.from_dict(d)
        assert c2.id == c.id
        assert c2.ttl_seconds == 900
        assert c2.status == ClaimStatus.RELEASED

    def test_roundtrip(self):
        c = self._make_claim()
        d = c.to_dict()
        c2 = Claim.from_dict(d)
        assert c2.to_dict() == d


# ── Reaction tests ──────────────────────────────────────────────────────


class TestReaction:
    def _make_reaction(self, **overrides):
        defaults = dict(
            session_id="sess-001",
            finding_id="f-abc123",
            agent_id="agent-2",
            expert_role="security",
            reaction=ReactionType.CONFIRM,
            reason="Verified: lock is indeed missing",
        )
        defaults.update(overrides)
        return Reaction(**defaults)

    def test_create_with_defaults(self):
        r = self._make_reaction()
        assert r.related_finding_id == ""
        assert r.created_at == ""

    def test_has_auto_generated_id(self):
        r = self._make_reaction()
        assert r.id.startswith("r-")
        assert len(r.id) == 8

    def test_id_uniqueness(self):
        ids = {self._make_reaction().id for _ in range(50)}
        assert len(ids) == 50

    def test_create_with_all_fields(self):
        r = self._make_reaction(
            related_finding_id="f-other1",
            created_at="2026-03-21T10:00:00+00:00",
        )
        assert r.related_finding_id == "f-other1"
        assert r.created_at == "2026-03-21T10:00:00+00:00"

    def test_to_dict(self):
        r = self._make_reaction()
        d = r.to_dict()
        assert isinstance(d, dict)
        assert d["reaction"] == "confirm"
        assert d["finding_id"] == "f-abc123"
        assert d["reason"] == "Verified: lock is indeed missing"

    def test_from_dict(self):
        r = self._make_reaction(reaction=ReactionType.DISPUTE)
        d = r.to_dict()
        r2 = Reaction.from_dict(d)
        assert r2.reaction == ReactionType.DISPUTE
        assert r2.session_id == r.session_id

    def test_roundtrip(self):
        r = self._make_reaction(
            reaction=ReactionType.DUPLICATE,
            related_finding_id="f-dup001",
            created_at="2026-03-21T12:00:00+00:00",
        )
        d = r.to_dict()
        r2 = Reaction.from_dict(d)
        assert r2.to_dict() == d
