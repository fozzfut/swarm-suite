# MCP server pattern

Every Swarm Suite tool exposes its API as an MCP server. The pattern is
codified in `swarm_core.mcp.MCPApp` so all tools handle transport,
error-wrapping, and logging the same way.

## Anatomy of a tool's `cli.py`

```python
import click
from swarm_core.logging_setup import setup_logging
from swarm_core.mcp import MCPApp
from .server import build_app   # returns a configured MCPApp

@click.group()
def main() -> None: ...

@main.command()
@click.option("--transport", default="stdio", type=click.Choice(["stdio", "sse"]))
@click.option("--port", default=8765, type=int)
@click.option("--debug", is_flag=True)
def serve(transport: str, port: int, debug: bool) -> None:
    setup_logging("review", debug=debug)
    app = build_app()
    # transport binding lives in the tool layer (see "Why" below)
    if transport == "stdio":
        from .server import run_stdio
        run_stdio(app)
    else:
        from .server import run_sse
        run_sse(app, port=port)
```

## Anatomy of a tool's `server.py`

```python
from swarm_core.mcp import MCPApp, mcp_safe

def build_app() -> MCPApp:
    app = MCPApp(name="review-swarm", version="0.4.0")

    @app.tool("post_finding", description="Post a finding for the current review session.")
    def post_finding(ctx: AppContext, session_id: str, finding: dict) -> dict:
        return ctx.session_manager.post_finding(session_id, finding)

    return app
```

`MCPApp.tool` decorator handles:
- registration in the app's tool table
- `mcp_safe` wrapping (catch ValueError -> McpError(INVALID_PARAMS); catch
  other exceptions -> McpError(INTERNAL_ERROR), with `exc_info=True` log)
- structured INFO log on tool entry/exit (arg names only -- never values)
- JSON Schema inference from the function signature

## Why the transport binding is in the tool layer, not in `MCPApp`

Each tool may need slightly different `Server` notification options
(e.g. ReviewSwarm uses MCP resource subscriptions for live finding
updates; FixSwarm doesn't). Putting the binding code inside each
`server.py` keeps these specifics visible per tool while the registry
and middleware (which ARE shared) live in `MCPApp`.

If we abstracted the binding into `MCPApp`, we'd grow a `notifications:`
parameter, then a `capabilities:` parameter, then a hook for "do X
before SSE accepts a connection" -- the abstraction would slowly become
a parallel re-implementation of `mcp.server.Server`. The current split
(registry in core, binding in tool) lets us keep `MCPApp` honest.

## Error handling contract

| Exception in tool handler | What the client sees |
|---------------------------|----------------------|
| `McpError` (raised by handler) | passes through unchanged |
| `ValueError`, `KeyError`, `TypeError` | `McpError(INVALID_PARAMS, str(exc))` |
| Anything else | `McpError(INTERNAL_ERROR, str(exc))` + log with `exc_info=True` |

Callers should NEVER let a raw exception bubble out of a tool handler --
the MCP server would crash, taking the whole session with it.

## Logging contract

`MCPApp` logs:
- `INFO  swarm.<tool> tool=<name> args=[<arg names>]` on entry
- `INFO  swarm.<tool> tool=<name> done` on success
- `ERROR swarm.<tool> Tool <name> raised` (with `exc_info=True`) on failure

Tool handlers log domain events at INFO; per-record DEBUG goes off by
default (set `SWARM_DEBUG=1` or `--debug` to enable).
