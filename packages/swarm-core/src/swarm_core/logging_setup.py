"""Single source of truth for Swarm Suite logging configuration.

Every package's `cli.py` calls `setup_logging(tool_name)` once at startup.
Get loggers via `get_logger(name)` -- never via `logging.getLogger(...)`
directly, which bypasses the rotation/format setup.

Log layout:
    ~/.swarm-kb/logs/<tool>.log     rotating daily, 30-day retention
    stderr                            WARNING+

Subsystem naming convention: `swarm.<tool>.<subsystem>` so a single
filter can suppress an entire tool's output if needed.

Debug level toggled by `SWARM_DEBUG=1` env var or `--debug` CLI flag.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_DEFAULT_LOG_DIR = Path.home() / ".swarm-kb" / "logs"
_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s :: %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_setup_done: dict[str, bool] = {}


def setup_logging(
    tool_name: str,
    *,
    debug: bool | None = None,
    log_dir: Path | None = None,
) -> None:
    """Configure logging for one tool. Idempotent per tool name.

    Args:
        tool_name: short name used in the log file (e.g. "review").
        debug: explicit override; falls back to SWARM_DEBUG env var.
        log_dir: override log directory (default ~/.swarm-kb/logs).
    """
    if _setup_done.get(tool_name):
        return

    if debug is None:
        debug = os.environ.get("SWARM_DEBUG", "").lower() in ("1", "true", "yes")

    log_dir = log_dir or _DEFAULT_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger(f"swarm.{tool_name}")
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.propagate = False  # avoid double-logging via stdlib root

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = TimedRotatingFileHandler(
        log_dir / f"{tool_name}.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    _setup_done[tool_name] = True


def get_logger(name: str) -> logging.Logger:
    """Return a child logger.

    `name` is appended after `swarm.<tool>` if it doesn't already start
    with `swarm.`. Pass either `"review.session_manager"` (preferred)
    or the bare module name; both end up under the configured root.
    """
    if name.startswith("swarm."):
        full = name
    else:
        full = f"swarm.{name}"
    return logging.getLogger(full)
