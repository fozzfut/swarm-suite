"""ReportRenderer ABC -- one method per output format.

Subclasses implement `render(session_id, fmt)`; the default `formats()`
lists what the subclass supports. Tools call `renderer.render(sid, "markdown")`
to get a string they can write to disk.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ReportRenderer(ABC):
    """Stateless renderer that takes a session_id and returns a string."""

    @abstractmethod
    def render(self, session_id: str, fmt: str = "markdown") -> str:
        ...

    def formats(self) -> list[str]:
        """Override to declare supported formats; defaults to markdown only."""
        return ["markdown"]
