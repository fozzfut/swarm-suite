# Coordination primitives

All in `swarm_core.coordination`. In-memory, thread-safe; persistence is
the caller's responsibility (typically through `swarm_kb` session storage).

## MessageBus

Topic-based pub/sub for agent-to-agent messages within one process.

```python
from swarm_core.coordination import MessageBus

bus = MessageBus()
bus.subscribe("findings.posted", lambda payload: ...)
bus.publish("findings.posted", {"id": "f-aa11"})
```

- Topics are free-form strings; convention: `<subsystem>.<event>`.
- Wildcard subscription is intentionally unsupported.
- Handlers run in the publisher's thread. Long-running handlers must
  offload (`bus` does not own a thread pool to avoid hidden ordering).
- Exception in one handler logs and does NOT block later handlers.

## EventBus

Per-session totally-ordered event log + push subscribers. Distinct from
`MessageBus` -- this is the audit timeline.

```python
from swarm_core.coordination import EventBus
from swarm_core.models import Event, EventType

bus = EventBus("sess-2026-04-26-001")
bus.append(Event(session_id="sess-...", event_type=EventType.PHASE_DONE.value))
bus.replay()  # full timeline
bus.subscribe(handler)  # push for new events
```

- `append` rejects events with a different `session_id` (LSP enforced).
- `replay()` returns a copy; safe to iterate while events arrive.

## PhaseBarrier

Tracks which experts have completed which phase of a multi-stage session.
Used by review/fix orchestration.

```python
from swarm_core.coordination import PhaseBarrier

b = PhaseBarrier()
b.mark_done("security", phase=1)
b.mark_done("performance", phase=1)
assert b.is_phase_ready(phase=1, required_experts=["security", "performance"])
```

- `mark_done` is idempotent.
- `is_phase_ready(phase, [])` is False -- empty required set is a misuse.

## ClaimRegistry

Atomic check-and-insert prevents two agents from working the same target.
The TOCTOU bug class this exists to prevent: two agents both call
`is_claimed(file)` -> False, both call `claim(file)`, both write.

```python
from swarm_core.coordination import ClaimRegistry

reg = ClaimRegistry()
claim = reg.try_claim("sess-...", "src/server.py", "security")  # Claim or None
if claim is None:
    raise ValueError("file already claimed")
...
reg.release("src/server.py", "security")
```

- `try_claim` is the only atomic API; never compose `is_claimed` + `claim`
  from outside the registry.
- `reap_expired()` flips ACTIVE-but-past-TTL claims to EXPIRED; call from
  a periodic task or before each `try_claim`.
- `restore(dicts)` reloads from persisted state.

## RateLimiter

Sliding-window rate limiter, keyed by arbitrary strings. Used by
`AppContext.finding_limiter` and `message_limiter` to prevent runaway
agents from flooding the KB.

```python
from swarm_core.coordination import RateLimiter

rl = RateLimiter(max_calls=60, window_seconds=60)
key = f"{session_id}:findings"
if not rl.check(key):
    raise McpError("rate limit exceeded; retry in N seconds")
```

- `check(key)` returns True AND records, or False if limit hit.
- `reset_prefix(f"{session_id}:")` releases counters when a session
  ends -- ESSENTIAL for long-running servers, otherwise memory grows.
