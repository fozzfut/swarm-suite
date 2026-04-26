"""MCPApp -- thin scaffolding to declare tools as decorated functions.

`MCPApp` lives at the boundary; its job is to:
  - Pick the transport (stdio / sse) from CLI args.
  - Wrap every tool in `mcp_safe` (uniform error handling).
  - Emit structured INFO logs on tool entry/exit (arg names only -- never
    values, which may include user code).
  - Provide a `run(transport)` method the tool's CLI calls.

Tool handlers are plain Python callables; the app does not impose async
on them. Async-aware tools can register coroutines just as well.

This is a deliberately thin facade. Tools that need MCP features beyond
"declare a tool, return a dict" should drop into the underlying `Server`
via `app.server` -- but that's an escape hatch, not the default.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    from mcp.server import Server
except ImportError:  # pragma: no cover
    Server = None  # type: ignore[assignment, misc]

from ..logging_setup import get_logger
from .errors import mcp_safe

_log = get_logger("core.mcp.app")


@dataclass
class _ToolDecl:
    name: str
    handler: Callable[..., Any]
    description: str
    schema: dict


@dataclass
class MCPApp:
    """Tiny decorator-based facade over `mcp.server.Server`."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    _tools: dict[str, _ToolDecl] = field(default_factory=dict)

    def tool(
        self,
        name: str | None = None,
        *,
        description: str = "",
        schema: dict | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator: register a Python callable as an MCP tool."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or func.__name__
            wrapped = mcp_safe(_with_logging(tool_name, func))
            self._tools[tool_name] = _ToolDecl(
                name=tool_name,
                handler=wrapped,
                description=description or (func.__doc__ or "").strip().splitlines()[0:1] and (func.__doc__ or "").strip().splitlines()[0] or tool_name,
                schema=schema or _infer_schema(func),
            )
            return wrapped

        return decorator

    def list_tool_names(self) -> list[str]:
        return sorted(self._tools.keys())

    def call(self, name: str, **kwargs: Any) -> Any:
        """Invoke a registered tool directly. Used by tests and CLIs."""
        decl = self._tools.get(name)
        if decl is None:
            raise KeyError(f"Tool {name!r} not registered on {self.name}")
        return decl.handler(**kwargs)

    # NOTE: `run(transport)` is intentionally not implemented here yet.
    # Each tool's CLI builds the `mcp.server.Server` and binds these
    # handlers; we keep the binding code in the tool layer so the
    # specifics of the server (notification options, capabilities)
    # remain visible per tool. `MCPApp` is the registry, not the runtime.

    @property
    def tools(self) -> dict[str, _ToolDecl]:
        return dict(self._tools)


# ----------------------------------------------------------------- helpers


def _with_logging(tool_name: str, func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap `func` to log entry/exit at INFO with arg names only."""
    sig = inspect.signature(func)
    arg_names = [p.name for p in sig.parameters.values()]

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        _log.info("tool=%s args=%s", tool_name, list(kwargs.keys()) or arg_names)
        result = func(*args, **kwargs)
        _log.info("tool=%s done", tool_name)
        return result

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def _infer_schema(func: Callable[..., Any]) -> dict:
    """Infer a basic JSON Schema from a Python signature.

    Best-effort: maps `str/int/float/bool/list/dict` to JSON types.
    Tools with rich schemas should pass `schema=` explicitly.
    """
    sig = inspect.signature(func)
    properties: dict[str, dict] = {}
    required: list[str] = []
    for pname, p in sig.parameters.items():
        if pname == "ctx":  # convention: AppContext is server-injected
            continue
        json_type = _python_to_json(p.annotation)
        properties[pname] = {"type": json_type}
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


_PYTHON_TO_JSON = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _python_to_json(annotation: Any) -> str:
    if annotation is inspect.Parameter.empty:
        return "string"
    origin = getattr(annotation, "__origin__", None)
    if origin in _PYTHON_TO_JSON:
        return _PYTHON_TO_JSON[origin]
    if annotation in _PYTHON_TO_JSON:
        return _PYTHON_TO_JSON[annotation]
    return "string"
