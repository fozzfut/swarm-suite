"""Session lifecycle template -- shared mkdir/meta/prune logic.

Every tool subclasses `SessionLifecycle` with its own `tool_name`,
`session_prefix`, and `initial_files`. Re-implementing the lifecycle
per tool is the pattern this module exists to prevent.
"""

from .lifecycle import SessionLifecycle

__all__ = ["SessionLifecycle"]
