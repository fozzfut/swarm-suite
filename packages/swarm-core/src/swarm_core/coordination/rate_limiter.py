"""Sliding-window rate limiter for MCP tool calls.

Prevents a runaway agent from flooding the KB with findings or messages
within a short window. Per-key counters; `reset_prefix` is essential to
release counters when a session ends (otherwise memory grows).
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    """Per-key sliding window rate limiter.

    `check(key)` returns True if the call is allowed AND records it; False
    if the limit is reached. Caller turns False into the appropriate
    user-facing response (typically an MCP error with message
    "rate limit exceeded; retry in N seconds").
    """

    def __init__(self, max_calls: int = 60, window_seconds: float = 60.0) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                return False
            bucket.append(now)
            return True

    def remaining(self, key: str) -> int:
        with self._lock:
            bucket = self._buckets.get(key)
            if not bucket:
                return self._max
            cutoff = time.monotonic() - self._window
            current = sum(1 for t in bucket if t >= cutoff)
            return max(0, self._max - current)

    def reset_prefix(self, prefix: str) -> int:
        """Remove every counter whose key starts with `prefix`. Returns count removed.

        Call on `end_session` with `prefix=f"{session_id}:"` to release
        memory for the finished session.
        """
        with self._lock:
            stale = [k for k in self._buckets if k.startswith(prefix)]
            for k in stale:
                del self._buckets[k]
            return len(stale)
