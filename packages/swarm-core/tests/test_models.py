"""Tests for swarm_core.models -- round-trip and severity ordering."""

from swarm_core.models import (
    Severity,
    SEVERITY_ORDER,
    severity_at_least,
    Reaction,
    ReactionType,
    Event,
    EventType,
    Message,
    MessageType,
    Claim,
    ClaimStatus,
)


def test_severity_ordering():
    assert SEVERITY_ORDER[0] == Severity.CRITICAL
    assert SEVERITY_ORDER[-1] == Severity.INFO
    assert severity_at_least(Severity.HIGH, Severity.MEDIUM)
    assert not severity_at_least(Severity.LOW, Severity.HIGH)


def test_reaction_round_trip():
    r = Reaction(
        session_id="sess-1",
        target_id="f-aa11",
        expert_role="security",
        reaction=ReactionType.CONFIRM,
        reason="agreed",
    )
    d = r.to_dict()
    back = Reaction.from_dict(d)
    assert back.session_id == r.session_id
    assert back.reaction == ReactionType.CONFIRM
    assert back.id == r.id


def test_event_assigns_id_and_timestamp():
    e = Event(session_id="sess-1", event_type=EventType.SESSION_STARTED.value)
    assert e.id.startswith("e-")
    assert e.timestamp


def test_message_broadcast_marker():
    m = Message(
        session_id="sess-1",
        from_agent="security",
        to_agent="*",
        message_type=MessageType.BROADCAST,
        content="hello",
    )
    assert m.to_agent == "*"
    assert Message.from_dict(m.to_dict()).content == "hello"


def test_claim_expiry_logic():
    c = Claim(session_id="sess-1", target_id="src/x.py", expert_role="dead-code", ttl_seconds=0)
    assert c.is_expired()
    assert c.status == ClaimStatus.ACTIVE  # status untouched until reaper runs
