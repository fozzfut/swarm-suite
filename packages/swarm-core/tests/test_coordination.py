"""Tests for coordination primitives."""

import time

import pytest

from swarm_core.coordination import (
    MessageBus,
    EventBus,
    PhaseBarrier,
    ClaimRegistry,
    RateLimiter,
)
from swarm_core.models import Event, EventType


def test_message_bus_pubsub():
    bus = MessageBus()
    seen = []
    bus.subscribe("findings.posted", lambda p: seen.append(p))
    bus.publish("findings.posted", {"id": "f-1"})
    assert seen == [{"id": "f-1"}]


def test_message_bus_handler_exception_does_not_block_others():
    bus = MessageBus()
    seen = []
    bus.subscribe("t", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    bus.subscribe("t", lambda p: seen.append(p))
    bus.publish("t", {"a": 1})
    assert seen == [{"a": 1}]


def test_event_bus_replay_and_subscribe():
    bus = EventBus("sess-1")
    seen = []
    bus.subscribe(seen.append)
    bus.append(Event(session_id="sess-1", event_type=EventType.SESSION_STARTED.value))
    bus.append(Event(session_id="sess-1", event_type=EventType.PHASE_DONE.value))
    assert bus.count() == 2
    assert len(seen) == 2
    assert len(bus.replay()) == 2


def test_event_bus_rejects_wrong_session():
    bus = EventBus("sess-1")
    with pytest.raises(ValueError):
        bus.append(Event(session_id="other", event_type="x"))


def test_phase_barrier_required_set():
    b = PhaseBarrier()
    b.mark_done("alpha", 1)
    b.mark_done("beta", 1)
    assert b.is_phase_ready(1, ["alpha", "beta"])
    assert not b.is_phase_ready(1, ["alpha", "beta", "gamma"])


def test_claim_registry_atomic():
    r = ClaimRegistry()
    a = r.try_claim("sess-1", "src/x.py", "alpha")
    b = r.try_claim("sess-1", "src/x.py", "beta")
    assert a is not None
    assert b is None
    assert r.release("src/x.py", "alpha")
    c = r.try_claim("sess-1", "src/x.py", "beta")
    assert c is not None


def test_rate_limiter_window():
    rl = RateLimiter(max_calls=3, window_seconds=0.5)
    for _ in range(3):
        assert rl.check("k")
    assert not rl.check("k")
    time.sleep(0.55)
    assert rl.check("k")


def test_rate_limiter_reset_prefix():
    rl = RateLimiter(max_calls=1, window_seconds=60)
    assert rl.check("sess-1:findings")
    assert not rl.check("sess-1:findings")
    n = rl.reset_prefix("sess-1:")
    assert n == 1
    assert rl.check("sess-1:findings")
