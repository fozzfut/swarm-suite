"""CLI entry point for swarm-kb."""

from __future__ import annotations

import json

import click

from swarm_core.logging_setup import setup_logging

from . import __version__
from .config import SuiteConfig


@click.group()
@click.version_option(__version__, prog_name="swarm-kb")
def main():
    """SwarmKB -- Shared knowledge base for the Swarm suite."""
    pass


@main.command()
@click.option("--port", default=8788, help="Port for SSE transport")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--transport", default="sse", type=click.Choice(["sse", "stdio"]))
def serve(port: int, host: str, transport: str):
    """Start the SwarmKB MCP server.

    On startup, automatically initializes directories and migrates
    legacy data from ~/.review-swarm, ~/.doc-swarm, etc.
    """
    setup_logging("kb")

    from .server import create_mcp_server

    mcp = create_mcp_server()

    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse", host=host, port=port)


@main.command()
def status():
    """Show KB status: session counts, storage root, xref count."""
    setup_logging("kb")

    config = SuiteConfig.load()

    from .bootstrap import bootstrap
    config = bootstrap(config)

    from .session_meta import count_sessions
    from .xref import XRefLog

    counts = count_sessions(config)
    xref_log = XRefLog(config.xrefs_path)

    click.echo(f"SwarmKB v{__version__}")
    click.echo(f"Storage: {config.kb_root}")
    click.echo(f"Config:  {config.config_file}")
    click.echo()
    click.echo("Sessions:")
    total = 0
    for tool, count in sorted(counts.items()):
        click.echo(f"  {tool:>8s}: {count}")
        total += count
    click.echo(f"  {'total':>8s}: {total}")
    click.echo(f"\nCross-references: {xref_log.count()}")


@main.command()
def migrate():
    """Migrate sessions from legacy storage paths to the shared KB."""
    setup_logging("kb")

    config = SuiteConfig.load()

    from .bootstrap import _ensure_dirs
    from .compat import migrate_all

    _ensure_dirs(config)
    result = migrate_all(config)

    total = sum(len(v) for v in result.values())
    if total:
        click.echo(f"Migrated {total} session(s):")
        for tool, ids in result.items():
            for sid in ids:
                click.echo(f"  [{tool}] {sid}")
    else:
        click.echo("No sessions to migrate.")


if __name__ == "__main__":
    main()
