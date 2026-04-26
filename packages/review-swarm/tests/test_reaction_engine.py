"""Tests for ReactionEngine -- consensus rules with confirm/dispute/extend/duplicate."""

import json

import pytest

from review_swarm.finding_store import FindingStore
from review_swarm.models import (
    Category,
    Finding,
    Reaction,
    ReactionType,
    Severity,
    Status,
)
from review_swarm.reaction_engine import ReactionEngine


def _make_finding(**overrides) -> Finding:
    """Create a Finding with reasonable defaults, accepting overrides."""
    defaults = {
        "id": Finding.generate_id(),
        "session_id": "sess-test-001",
        "expert_role": "thread-safety",
        "agent_id": "agent-001",
        "file": "src/main.py",
        "line_start": 10,
        "line_end": 20,
        "snippet": "x = shared_state",
        "severity": Severity.MEDIUM,
        "category": Category.BUG,
        "title": "Unprotected shared state",
        "confidence": 0.7,
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _make_engine(tmp_path, confirm_threshold=2):
    """Create a FindingStore + ReactionEngine with temp files."""
    store = FindingStore(tmp_path / "findings.jsonl")
    engine = ReactionEngine(
        store=store,
        reactions_path=tmp_path / "reactions.jsonl",
        confirm_threshold=confirm_threshold,
    )
    return store, engine


def _make_reaction(finding_id, reaction_type, **overrides):
    """Create a Reaction with reasonable defaults."""
    defaults = {
        "session_id": "sess-test-001",
        "finding_id": finding_id,
        "agent_id": "agent-002",
        "expert_role": "security",
        "reaction": reaction_type,
        "reason": "Verified the issue",
    }
    defaults.update(overrides)
    return Reaction(**defaults)


class TestReactionEngineConsensus:
    def test_two_confirms_to_confirmed(self, tmp_path):
        """1 confirm = still OPEN, 2nd confirm from different expert = CONFIRMED."""
        store, engine = _make_engine(tmp_path)
        finding = _make_finding()
        store.post(finding)

        # First confirm -- still OPEN
        r1 = _make_reaction(finding.id, ReactionType.CONFIRM, expert_role="security", agent_id="agent-002")
        updated = engine.react(r1)
        assert updated.status == Status.OPEN

        # Second confirm from different expert -- now CONFIRMED
        r2 = _make_reaction(finding.id, ReactionType.CONFIRM, expert_role="performance", agent_id="agent-003")
        updated = engine.react(r2)
        assert updated.status == Status.CONFIRMED

    def test_one_dispute_to_disputed(self, tmp_path):
        """Single dispute -> DISPUTED."""
        store, engine = _make_engine(tmp_path)
        finding = _make_finding()
        store.post(finding)

        r = _make_reaction(finding.id, ReactionType.DISPUTE)
        updated = engine.react(r)
        assert updated.status == Status.DISPUTED

    def test_dispute_overrides_confirms(self, tmp_path):
        """2 confirms -> CONFIRMED, then 1 dispute -> DISPUTED."""
        store, engine = _make_engine(tmp_path)
        finding = _make_finding()
        store.post(finding)

        # Two confirms from different experts -> CONFIRMED
        engine.react(
            _make_reaction(finding.id, ReactionType.CONFIRM, expert_role="security", agent_id="agent-002")
        )
        updated = engine.react(
            _make_reaction(finding.id, ReactionType.CONFIRM, expert_role="performance", agent_id="agent-003")
        )
        assert updated.status == Status.CONFIRMED

        # One dispute from yet another expert overrides -> DISPUTED
        updated = engine.react(
            _make_reaction(finding.id, ReactionType.DISPUTE, expert_role="design", agent_id="agent-004")
        )
        assert updated.status == Status.DISPUTED

    def test_duplicate_links_findings(self, tmp_path):
        """Duplicate reaction links both findings, status=DUPLICATE."""
        store, engine = _make_engine(tmp_path)
        f1 = _make_finding()
        f2 = _make_finding()
        store.post(f1)
        store.post(f2)

        r = _make_reaction(
            f1.id,
            ReactionType.DUPLICATE,
            related_finding_id=f2.id,
        )
        updated = engine.react(r)

        # f1 should be DUPLICATE and linked to f2
        assert updated.status == Status.DUPLICATE
        assert f2.id in updated.related_findings

        # f2 should be linked back to f1 (bidirectional)
        f2_updated = store.get_by_id(f2.id)
        assert f2_updated is not None
        assert f1.id in f2_updated.related_findings

    def test_extend_links_without_status_change(self, tmp_path):
        """Extend links but keeps status=OPEN."""
        store, engine = _make_engine(tmp_path)
        f1 = _make_finding()
        f2 = _make_finding()
        store.post(f1)
        store.post(f2)

        r = _make_reaction(
            f1.id,
            ReactionType.EXTEND,
            related_finding_id=f2.id,
        )
        updated = engine.react(r)

        # Status stays OPEN
        assert updated.status == Status.OPEN

        # Bidirectional links created
        assert f2.id in updated.related_findings
        f2_updated = store.get_by_id(f2.id)
        assert f2_updated is not None
        assert f1.id in f2_updated.related_findings


class TestReactionEngineErrors:
    def test_react_to_nonexistent_finding_raises(self, tmp_path):
        """KeyError when finding_id does not exist."""
        _store, engine = _make_engine(tmp_path)

        r = _make_reaction("f-nonexistent", ReactionType.CONFIRM)
        with pytest.raises(KeyError, match="f-nonexistent"):
            engine.react(r)

    def test_duplicate_reaction_from_same_expert_raises(self, tmp_path):
        """ValueError when same expert submits same reaction type twice."""
        store, engine = _make_engine(tmp_path)
        finding = _make_finding()
        store.post(finding)

        r1 = _make_reaction(
            finding.id, ReactionType.CONFIRM,
            expert_role="security", agent_id="agent-002",
        )
        engine.react(r1)

        # Same expert_role + same reaction type -> duplicate
        r2 = _make_reaction(
            finding.id, ReactionType.CONFIRM,
            expert_role="security", agent_id="agent-002",
        )
        with pytest.raises(ValueError, match="Duplicate reaction"):
            engine.react(r2)

    def test_same_expert_different_reaction_type_allowed(self, tmp_path):
        """Same expert can submit different reaction types on the same finding."""
        store, engine = _make_engine(tmp_path)
        finding = _make_finding()
        store.post(finding)

        r1 = _make_reaction(
            finding.id, ReactionType.CONFIRM,
            expert_role="security", agent_id="agent-002",
        )
        engine.react(r1)

        # Same expert_role but different reaction type -> allowed
        r2 = _make_reaction(
            finding.id, ReactionType.DISPUTE,
            expert_role="security", agent_id="agent-002",
        )
        updated = engine.react(r2)
        assert updated.status == Status.DISPUTED


class TestReactionEnginePersistence:
    def test_reactions_persisted(self, tmp_path):
        """reactions.jsonl has the reaction line after react()."""
        store, engine = _make_engine(tmp_path)
        finding = _make_finding()
        store.post(finding)

        r = _make_reaction(finding.id, ReactionType.CONFIRM)
        engine.react(r)

        reactions_path = tmp_path / "reactions.jsonl"
        assert reactions_path.exists()
        lines = reactions_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["finding_id"] == finding.id
        assert data["reaction"] == "confirm"
        assert data["created_at"] != ""


class TestReactionEngineCustomThreshold:
    def test_custom_threshold(self, tmp_path):
        """With threshold=1, a single confirm = CONFIRMED."""
        store, engine = _make_engine(tmp_path, confirm_threshold=1)
        finding = _make_finding()
        store.post(finding)

        r = _make_reaction(finding.id, ReactionType.CONFIRM)
        updated = engine.react(r)
        assert updated.status == Status.CONFIRMED
