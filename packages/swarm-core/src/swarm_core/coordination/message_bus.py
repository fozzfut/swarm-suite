"""In-process pub/sub bus for agent-to-agent messages.

Single bus per session. Subscribers register handlers per topic; handlers
run in the publisher's thread. Long-running handlers must offload (the
bus does not own a thread pool to avoid hidden ordering surprises).

Two surfaces:
  * `publish(topic, payload)` -- raw dict, for legacy / arbitrary payloads.
  * `publish_structured(topic, content, background, intermediate_output, **meta)`
    -- enforces the swarms-style triple so a late-joining or restarted
    subscriber can resume from one event without rehydrating prior state.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable, TypedDict

from ..logging_setup import get_logger

_log = get_logger("core.message_bus")

Handler = Callable[[dict], None]


class StructuredPayload(TypedDict, total=False):
    """The swarms-style triple plus optional metadata.

    `content` is the message itself (what the publisher is saying now).
    `background` is the persistent task context (goal, role, inputs).
    `intermediate_output` is the most recent upstream result the
    receiver needs to act on. Anything else (correlation_id, source,
    timestamp) goes alongside as additional keys.
    """

    content: Any
    background: dict
    intermediate_output: dict


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

    def publish_structured(
        self,
        topic: str,
        *,
        content: Any,
        background: dict | None = None,
        intermediate_output: dict | None = None,
        **meta: Any,
    ) -> dict:
        """Publish the swarms-style triple as a single payload dict.

        Returns the payload that was sent (useful for tests and for
        callers that also want to persist it). Extra keyword arguments
        (`correlation_id`, `from_agent`, ...) land in the payload
        alongside the triple.
        """
        payload: dict = {
            "content": content,
            "background": dict(background or {}),
            "intermediate_output": dict(intermediate_output or {}),
            **meta,
        }
        self.publish(topic, payload)
        return payload

    def topics(self) -> list[str]:
        with self._lock:
            return [t for t, hs in self._subscribers.items() if hs]


def is_structured_payload(payload: dict) -> bool:
    """True if `payload` carries the swarms-style triple keys.

    Use in subscribers that need to distinguish structured publishes
    from legacy raw-dict publishes.
    """
    return (
        isinstance(payload, dict)
        and "content" in payload
        and "background" in payload
        and "intermediate_output" in payload
    )
