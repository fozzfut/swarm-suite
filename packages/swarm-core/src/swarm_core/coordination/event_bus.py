"""Append-only session event log with replay.

Distinct from `MessageBus`: `EventBus` is a totally-ordered timeline of
state changes inside one session, suitable for audit and for clients
that subscribe via MCP resource subscriptions to "see" the swarm work.
"""

from __future__ import annotations

import threading
from typing import Callable

from ..models.event import Event

EventHandler = Callable[[Event], None]


class EventBus:
    """Per-session append-only event log + push subscribers.

    `append` is the write path; `replay` returns the full timeline;
    `subscribe` lets a caller receive events as they arrive.
    """

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._events: list[Event] = []
        self._handlers: list[EventHandler] = []
        self._lock = threading.RLock()

    @property
    def session_id(self) -> str:
        return self._session_id

    def append(self, event: Event) -> None:
        if event.session_id != self._session_id:
            raise ValueError(
                f"Event for session {event.session_id!r} cannot be appended "
                f"to EventBus({self._session_id!r})"
            )
        with self._lock:
            self._events.append(event)
            handlers = list(self._handlers)
        for h in handlers:
            h(event)

    def replay(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def subscribe(self, handler: EventHandler) -> None:
        with self._lock:
            self._handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        with self._lock:
            try:
                self._handlers.remove(handler)
            except ValueError:
                pass

    def count(self) -> int:
        with self._lock:
            return len(self._events)
