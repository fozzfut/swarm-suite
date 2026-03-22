---
title: Event Bus
type: api
status: draft
source_files:
- src/review_swarm/event_bus.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/event_bus.py
lines_of_code: 141
classes:
- SessionEventBus
functions: []
---

# Event Bus

SessionEventBus -- asyncio-based event publication and subscription per session.

**Source:** `src/review_swarm/event_bus.py` | **Lines:** 141

## Dependencies

- `__future__`
- `asyncio`
- `json`
- `logging_config`
- `models`
- `pathlib`
- `threading`

## Classes

### `class SessionEventBus`

Asyncio event bus for a single review session.

Subscribers receive events via asyncio.Queue instances.
Events are persisted to events.jsonl for durability and polling.

Two publish methods:
  - publish_sync(): persists to memory + disk only (no async fan-out)
  - publish(): persists + fans out to async subscriber queues

**Lines:** 16-141

**Methods:**

- `def publish_sync(self, event_type: EventType, payload: dict) -> Event` — Synchronous publish: memory + disk, no async queue fan-out.
- `async def publish(self, event_type: EventType, payload: dict) -> Event` — Async publish: persist + fan out to all subscriber queues.
- `def subscribe(self, subscriber_id: str, max_queue: int=256) -> asyncio.Queue[Event]` — Register a subscriber, return its event queue.
- `def unsubscribe(self, subscriber_id: str) -> None` — Remove a subscriber.
- `def subscriber_count(self) -> int`
- `def get_events(self, since: str | None=None, event_type: EventType | None=None) -> list[dict]` — Return events since a timestamp, optionally filtered by type.
- `def event_count(self) -> int`
