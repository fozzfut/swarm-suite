"""Logging adapter -- delegates to swarm_core.logging_setup (single source of truth).

Kept as a thin wrapper so existing `from .logging_config import get_logger`
call sites continue to work while the actual configuration (rotating file
handler, structured format, SWARM_DEBUG toggle) lives in swarm_core.
"""

from __future__ import annotations

import logging

from swarm_core.logging_setup import (
    get_logger as _core_get_logger,
    setup_logging as _core_setup_logging,
)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure review-swarm logging via swarm_core."""
    debug = level.upper() == "DEBUG"
    _core_setup_logging("review", debug=debug)
    return logging.getLogger("swarm.review")


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the swarm.review namespace."""
    return _core_get_logger(f"review.{name}")
