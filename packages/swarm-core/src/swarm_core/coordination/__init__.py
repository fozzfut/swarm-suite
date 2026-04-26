"""Concurrency primitives for multi-agent swarms.

All classes here are in-memory and thread-safe. Persistence is the
caller's responsibility -- typically via swarm_kb session storage.
"""

from .message_bus import MessageBus, StructuredPayload, is_structured_payload
from .event_bus import EventBus
from .phase_barrier import PhaseBarrier
from .claim_registry import ClaimRegistry
from .rate_limiter import RateLimiter
from .completion import (
    CapExceededError,
    CompletionTracker,
    DEFAULT_MAX_CONSECUTIVE_THINKS,
    DEFAULT_MAX_SUBTASKS,
    DEFAULT_MAX_SUBTASK_LOOPS,
)

__all__ = [
    "MessageBus",
    "StructuredPayload",
    "is_structured_payload",
    "EventBus",
    "PhaseBarrier",
    "ClaimRegistry",
    "RateLimiter",
    "CompletionTracker",
    "CapExceededError",
    "DEFAULT_MAX_SUBTASKS",
    "DEFAULT_MAX_SUBTASK_LOOPS",
    "DEFAULT_MAX_CONSECUTIVE_THINKS",
]
