"""In-process pub/sub bus for agent-to-agent messages.

Single bus per session. Subscribers register handlers per topic; handlers
run in the publisher's thread. Long-running handlers must offload (the
bus does not own a thread pool to avoid hidden ordering surprises).
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Callable

from ..logging_setup import get_logger

_log = get_logger("core.message_bus")

Handler = Callable[[dict], None]


class MessageBus:
    """Topic-based message bus.

    Topics are free-form strings; convention is `<subsystem>.<event>`,
    e.g. `findings.posted` or `claims.released`. Wildcard subscription
    (`"*"`) is intentionally unsupported -- explicit topics force
    callers to think about coupling.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.RLock()

    def subscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            if topic in self._subscribers:
                try:
                    self._subscribers[topic].remove(handler)
                except ValueError:
                    pass

    def publish(self, topic: str, payload: dict) -> None:
        """Deliver `payload` to every subscriber of `topic`.

        Handlers are invoked outside the bus lock; an exception in one
        handler is logged and does NOT prevent later handlers from
        running.
        """
        with self._lock:
            handlers = list(self._subscribers.get(topic, ()))
        for h in handlers:
            try:
                h(payload)
            except Exception:
                _log.exception("Handler for %s raised; continuing", topic)

    def topics(self) -> list[str]:
        with self._lock:
            return [t for t, hs in self._subscribers.items() if hs]
