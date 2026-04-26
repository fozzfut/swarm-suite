"""Uniform MCP error conversion.

Tools raise plain `ValueError` / `FileNotFoundError` / domain exceptions.
The MCP boundary converts them to `McpError` so the client gets a clean
error response instead of the server crashing.

Use `@mcp_safe` on tool handlers as a decorator OR call `to_mcp_error`
inside an `except` block.
"""

from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

try:
    from mcp.shared.exceptions import McpError
    from mcp.types import ErrorData, INTERNAL_ERROR, INVALID_PARAMS
except ImportError:  # pragma: no cover -- guard for tests without mcp installed
    McpError = Exception  # type: ignore[assignment, misc]
    ErrorData = None  # type: ignore[assignment]
    INTERNAL_ERROR = -32603
    INVALID_PARAMS = -32602

from ..logging_setup import get_logger

_log = get_logger("core.mcp.errors")

F = TypeVar("F", bound=Callable[..., Any])


def to_mcp_error(exc: Exception) -> "McpError":
    """Convert a Python exception into an MCP error.

    `ValueError` -> INVALID_PARAMS (the client can fix it).
    Anything else -> INTERNAL_ERROR (server-side issue).
    """
    if ErrorData is None:  # pragma: no cover
        return McpError(str(exc))
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        code = INVALID_PARAMS
    else:
        code = INTERNAL_ERROR
    return McpError(ErrorData(code=code, message=str(exc) or type(exc).__name__))


def mcp_safe(func: F) -> F:
    """Decorator: catch known exceptions and re-raise as McpError.

    Logs the original exception with `exc_info=True` before converting.
    `McpError` instances pass through unchanged.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except McpError:
            raise
        except Exception as exc:
            _log.exception("Tool %s raised", func.__name__)
            raise to_mcp_error(exc) from exc

    return wrapper  # type: ignore[return-value]
