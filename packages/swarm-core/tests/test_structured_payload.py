"""Tests for structured (Message, Background, Intermediate-Output) payloads."""

from __future__ import annotations

import pytest

from swarm_core.coordination import (
    MessageBus,
    StructuredPayload,
    is_structured_payload,
)
from swarm_core.models import Message, MessageType, MESSAGE_SCHEMA_VERSION


def test_message_round_trips_new_fields():
    m = Message(
        session_id="sess-1",
        from_agent="a",
        to_agent="b",
        message_type=MessageType.DIRECT,
        content="hi",
        background={"goal": "review file"},
        intermediate_output={"prev_finding": "f-x1y2"},
    )
    d = m.to_dict()
    assert d["schema_version"] == MESSAGE_SCHEMA_VERSION
    assert d["background"] == {"goal": "review file"}
    assert d["intermediate_output"] == {"prev_finding": "f-x1y2"}
    rebuilt = Message.from_dict(d)
    assert rebuilt.background == {"goal": "review file"}
    assert rebuilt.intermediate_output == {"prev_finding": "f-x1y2"}


def test_message_from_old_dict_keeps_working():
    """Schema-version=1 payload must load without raising; new fields default empty."""
    legacy = {
        "id": "m-old1",
        "session_id": "sess-1",
        "from_agent": "a",
        "to_agent": "b",
        "message_type": "direct",
        "content": "legacy",
        "in_reply_to": "",
        "urgent": False,
        "context": {"finding_id": "f-1"},
        "created_at": "2025-01-01T00:00:00+00:00",
    }
    m = Message.from_dict(legacy)
    assert m.content == "legacy"
    assert m.context == {"finding_id": "f-1"}
    assert m.background == {}
    assert m.intermediate_output == {}
    assert m.schema_version == 1  # preserved -- forward compat


def test_to_structured_payload_extracts_triple():
    m = Message(
        session_id="sess-1",
        from_agent="a",
        to_agent="b",
        message_type=MessageType.DIRECT,
        content="run tests",
        background={"goal": "verify fix"},
        intermediate_output={"diff": "..."},
    )
    triple = m.to_structured_payload()
    assert triple == {
        "content": "run tests",
        "background": {"goal": "verify fix"},
        "intermediate_output": {"diff": "..."},
    }


def test_publish_structured_delivers_triple():
    bus = MessageBus()
    received: list[dict] = []
    bus.subscribe("review.next", received.append)
    sent = bus.publish_structured(
        "review.next",
        content="check sec/auth.py",
        background={"goal": "security audit"},
        intermediate_output={"prev_file": "sec/login.py"},
        from_agent="security-expert",
    )
    assert received == [sent]
    payload = received[0]
    assert payload["content"] == "check sec/auth.py"
    assert payload["background"] == {"goal": "security audit"}
    assert payload["intermediate_output"] == {"prev_file": "sec/login.py"}
    assert payload["from_agent"] == "security-expert"


def test_publish_structured_defaults_empty_dicts():
    bus = MessageBus()
    received: list[dict] = []
    bus.subscribe("t", received.append)
    bus.publish_structured("t", content="hi")
    assert received[0] == {"content": "hi", "background": {}, "intermediate_output": {}}


def test_is_structured_payload_recognises_triple():
    assert is_structured_payload({
        "content": "x",
        "background": {},
        "intermediate_output": {},
    })
    assert not is_structured_payload({"content": "x"})
    assert not is_structured_payload({"random": "dict"})
    assert not is_structured_payload(None)  # type: ignore[arg-type]


def test_legacy_publish_still_works():
    """Raw publish() must keep accepting arbitrary dicts."""
    bus = MessageBus()
    seen: list[dict] = []
    bus.subscribe("t", seen.append)
    bus.publish("t", {"any": "shape", "nested": {"k": "v"}})
    assert seen == [{"any": "shape", "nested": {"k": "v"}}]
    assert not is_structured_payload(seen[0])
