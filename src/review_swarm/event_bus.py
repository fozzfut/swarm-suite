"""SessionEventBus -- asyncio-based event publication and subscription per session."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from .logging_config import get_logger
from .models import Event, EventType, now_iso

_log = get_logger("event_bus")


class SessionEventBus:
    """Asyncio event bus for a single review session.

    Subscribers receive events via asyncio.Queue instances.
    Events are persisted to events.jsonl for durability and polling.

    Two publish methods:
      - publish_sync(): persists to memory + disk only (no async fan-out)
      - publish(): persists + fans out to async subscriber queues
    """

    def __init__(self, session_id: str, events_path: Path, max_events: int = 50_000) -> None:
        self._session_id = session_id
        self._events_path = Path(events_path)
        self._max_events = max_events
        self._events: list[Event] = []
        self._subscribers: dict[str, asyncio.Queue[Event]] = {}
        self._lock = threading.Lock()
        self._load()

    # ── Publishing ───────────────────────────────────────────────────

    def publish_sync(self, event_type: EventType, payload: dict) -> Event:
        """Synchronous publish: memory + disk, no async queue fan-out.

        Safe to call from sync code. Tests and direct tool_* calls use this.
        """
        with self._lock:
            event = Event(
                id=Event.generate_id(),
                event_type=event_type,
                session_id=self._session_id,
                timestamp=now_iso(),
                payload=payload,
            )
            self._events.append(event)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events:]
            self._append_to_disk(event)
            _log.debug("Event %s published: %s", event.id, event_type.value)
            return event

    async def publish(self, event_type: EventType, payload: dict) -> Event:
        """Async publish: persist + fan out to all subscriber queues."""
        event = self.publish_sync(event_type, payload)
        await self._fan_out(event)
        return event

    async def _fan_out(self, event: Event) -> None:
        """Push event to all subscriber queues (non-blocking)."""
        with self._lock:
            items = list(self._subscribers.items())
        for sub_id, queue in items:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                _log.warning("QueueFull for subscriber %s, event dropped", sub_id)

    # ── Subscription ─────────────────────────────────────────────────

    def subscribe(self, subscriber_id: str, max_queue: int = 256) -> asyncio.Queue[Event]:
        """Register a subscriber, return its event queue."""
        with self._lock:
            if subscriber_id not in self._subscribers:
                self._subscribers[subscriber_id] = asyncio.Queue(maxsize=max_queue)
            return self._subscribers[subscriber_id]

    def unsubscribe(self, subscriber_id: str) -> None:
        """Remove a subscriber."""
        with self._lock:
            self._subscribers.pop(subscriber_id, None)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # ── Polling / Query ──────────────────────────────────────────────

    def get_events(
        self,
        since: str | None = None,
        event_type: EventType | None = None,
    ) -> list[dict]:
        """Return events since a timestamp, optionally filtered by type.

        Polling fallback for clients that don't support MCP subscriptions.
        """
        with self._lock:
            results: list[Event] = self._events
            if since:
                results = [e for e in results if e.timestamp > since]
            if event_type:
                results = [e for e in results if e.event_type == event_type]
            return [e.to_dict() for e in results]

    def event_count(self) -> int:
        return len(self._events)

    # ── Persistence ──────────────────────────────────────────────────

    def _append_to_disk(self, event: Event) -> None:
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict()) + "\n")

    def _load(self) -> None:
        if not self._events_path.exists():
            return
        with open(self._events_path, "r", encoding="utf-8") as fh:
            for line_num, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if not isinstance(data, dict):
                        _log.warning(
                            "Expected dict, got %s on line %d in %s",
                            type(data).__name__, line_num, self._events_path,
                        )
                        continue
                    self._events.append(Event.from_dict(data))
                except (json.JSONDecodeError, KeyError, ValueError) as exc:
                    _log.warning(
                        "Skipping corrupt line %d in %s: %s", line_num, self._events_path, exc
                    )
