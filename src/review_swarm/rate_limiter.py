"""Simple sliding-window rate limiter per agent."""

from __future__ import annotations

import time
import threading
from collections import defaultdict


class RateLimiter:
    """Per-agent sliding window rate limiter.

    Tracks call timestamps per agent_key. Rejects calls that exceed
    max_calls within window_seconds.
    """

    def __init__(self, max_calls: int = 60, window_seconds: float = 60.0) -> None:
        self._max_calls = max_calls
        self._window = window_seconds
        self._calls: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, agent_key: str) -> None:
        """Check if agent can make a call. Raises ValueError if rate exceeded."""
        now = time.monotonic()
        with self._lock:
            calls = self._calls[agent_key]
            # Prune old entries
            cutoff = now - self._window
            self._calls[agent_key] = [t for t in calls if t > cutoff]
            calls = self._calls[agent_key]

            if len(calls) >= self._max_calls:
                raise ValueError(
                    f"Rate limit exceeded for {agent_key}: "
                    f"max {self._max_calls} calls per {self._window}s"
                )
            calls.append(now)

    def reset(self, agent_key: str | None = None) -> None:
        """Reset rate limiter for one agent or all agents."""
        with self._lock:
            if agent_key:
                self._calls.pop(agent_key, None)
            else:
                self._calls.clear()
