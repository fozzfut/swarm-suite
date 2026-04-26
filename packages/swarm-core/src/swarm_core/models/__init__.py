"""Canonical enums and base dataclasses shared across the suite.

Tools may extend these (subclass enums via composition, wrap dataclasses)
but MUST NOT redeclare them. The single source of truth lives here so a
`Severity.HIGH` from `review-swarm` is the same value as `Severity.HIGH`
in `fix-swarm`'s storage.
"""

from .severity import Severity, SEVERITY_ORDER, severity_at_least
from .reaction import ReactionType, Reaction
from .event import EventType, Event
from .message import MessageType, Message
from .claim import ClaimStatus, Claim

__all__ = [
    "Severity",
    "SEVERITY_ORDER",
    "severity_at_least",
    "ReactionType",
    "Reaction",
    "EventType",
    "Event",
    "MessageType",
    "Message",
    "ClaimStatus",
    "Claim",
]
