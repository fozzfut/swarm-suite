"""Phase barrier -- coordinates multi-expert pipeline phases.

A phase is "done" when every required expert has called `mark_done`.
Used by review/fix/spec orchestration to know when to advance from
"propose" -> "critique" -> "vote" -> "resolve" without auto-advancing.
"""

from __future__ import annotations

import threading
from typing import Iterable


class PhaseBarrier:
    """Track which experts have completed which phase of a session.

    `phases_done[expert_role]` is a set of phase ints the expert has
    finished. `is_phase_ready(phase, required_experts)` returns True
    when every required expert has marked that phase done.
    """

    def __init__(self) -> None:
        self._done: dict[str, set[int]] = {}
        self._lock = threading.RLock()

    def mark_done(self, expert_role: str, phase: int) -> None:
        with self._lock:
            self._done.setdefault(expert_role, set()).add(phase)

    def is_phase_ready(self, phase: int, required_experts: Iterable[str]) -> bool:
        required = list(required_experts)
        if not required:
            return False
        with self._lock:
            return all(phase in self._done.get(role, set()) for role in required)

    def status(self, required_experts: Iterable[str]) -> dict[str, list[int]]:
        with self._lock:
            return {
                role: sorted(self._done.get(role, set()))
                for role in required_experts
            }

    def to_dict(self) -> dict[str, list[int]]:
        with self._lock:
            return {role: sorted(phases) for role, phases in self._done.items()}

    @classmethod
    def from_dict(cls, data: dict[str, list[int]]) -> "PhaseBarrier":
        b = cls()
        for role, phases in data.items():
            b._done[role] = set(phases)
        return b
