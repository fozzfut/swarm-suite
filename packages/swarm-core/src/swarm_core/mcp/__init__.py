"""MCP server scaffolding shared across tools.

Use `MCPApp` to register tools instead of hand-rolling `Server()`. The
app handles transport selection (stdio / sse), uniform error wrapping,
structured logging, and rate-limiting middleware.
"""

from .app import MCPApp
from .errors import to_mcp_error, mcp_safe

__all__ = ["MCPApp", "to_mcp_error", "mcp_safe"]
