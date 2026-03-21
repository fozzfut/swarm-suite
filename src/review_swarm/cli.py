"""CLI entry point for ReviewSwarm."""

from __future__ import annotations

import shutil
from pathlib import Path

import click

from . import __version__
from .config import Config


@click.group()
@click.version_option(__version__, prog_name="ReviewSwarm")
def main():
    """ReviewSwarm -- Collaborative AI Code Review MCP Server."""
    pass


@main.command()
@click.option("--port", default=8787, help="Port for SSE transport")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--transport", default="sse", type=click.Choice(["sse", "stdio"]))
def serve(port: int, host: str, transport: str):
    """Start the ReviewSwarm MCP server."""
    from .server import create_mcp_server

    mcp = create_mcp_server()

    click.echo(f"ReviewSwarm v{__version__} starting on {transport}...")
    if transport == "sse":
        click.echo(f"Listening on http://{host}:{port}/sse")
        mcp.run(transport="sse", host=host, port=port)
    else:
        mcp.run(transport="stdio")


@main.command("list-sessions")
def list_sessions():
    """List all review sessions."""
    config = Config.load()
    from .session_manager import SessionManager

    mgr = SessionManager(config)
    sessions = mgr.list_sessions()

    if not sessions:
        click.echo("No sessions found.")
        return

    for s in sessions:
        status = s.get("status", "unknown")
        name = s.get("name", s["session_id"])
        click.echo(f"  {s['session_id']}  [{status}]  {name}")


@main.command()
@click.option("--force", is_flag=True, help="Overwrite existing config")
def init(force: bool):
    """Create default config at ~/.review-swarm/config.yaml."""
    config_path = Path("~/.review-swarm/config.yaml").expanduser()
    if config_path.exists() and not force:
        click.echo(f"Config already exists: {config_path}")
        click.echo("Use --force to overwrite.")
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    default = Config()
    config_path.write_text(default.to_yaml(), encoding="utf-8")

    # Ensure custom experts dir exists
    Path(default.experts.custom_dir).expanduser().mkdir(parents=True, exist_ok=True)

    click.echo(f"Config created: {config_path}")
    click.echo(f"Custom experts dir: {Path(default.experts.custom_dir).expanduser()}")


@main.command()
@click.argument("session_id")
@click.option("--format", "fmt", default="markdown", type=click.Choice(["markdown", "json"]))
def report(session_id: str, fmt: str):
    """Generate a report for an existing session."""
    config = Config.load()
    from .session_manager import SessionManager
    from .report_generator import ReportGenerator

    mgr = SessionManager(config)
    try:
        store = mgr.get_finding_store(session_id)
    except KeyError:
        click.echo(f"Session not found: {session_id}", err=True)
        raise SystemExit(1)

    gen = ReportGenerator(store)
    click.echo(gen.generate(session_id, fmt=fmt))


@main.command()
@click.option("--older-than", "days", default=30, type=int, help="Delete sessions older than N days")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted")
def purge(days: int, dry_run: bool):
    """Delete old completed sessions."""
    import json
    from datetime import datetime, timedelta, timezone

    config = Config.load()
    sessions_path = config.sessions_path
    if not sessions_path.exists():
        click.echo("No sessions directory found.")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = 0

    for sess_dir in sorted(sessions_path.iterdir()):
        if not sess_dir.is_dir():
            continue
        meta_file = sess_dir / "meta.json"
        if not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        if meta.get("status") != "completed":
            continue

        created = meta.get("created_at", "")
        if not created:
            continue
        try:
            created_dt = datetime.fromisoformat(created)
        except ValueError:
            continue

        if created_dt < cutoff:
            sid = meta.get("session_id", sess_dir.name)
            if dry_run:
                click.echo(f"  would delete: {sid} (created {created[:10]})")
            else:
                shutil.rmtree(sess_dir)
                click.echo(f"  deleted: {sid}")
            deleted += 1

    if deleted == 0:
        click.echo(f"No completed sessions older than {days} days.")
    elif dry_run:
        click.echo(f"\n{deleted} session(s) would be deleted. Run without --dry-run to delete.")
    else:
        click.echo(f"\n{deleted} session(s) deleted.")


@main.command()
@click.argument("expert_name", required=False)
@click.option("--list", "list_all", is_flag=True, help="List available experts")
def prompt(expert_name: str | None, list_all: bool):
    """Print the system prompt for an expert (for setting up AI agents)."""
    from .expert_profiler import ExpertProfiler

    profiler = ExpertProfiler()

    if list_all or expert_name is None:
        profiles = profiler.list_profiles()
        click.echo("Available expert profiles:\n")
        for p in profiles:
            source = Path(p.get("_source_file", "")).stem
            desc = p.get("description", "")
            click.echo(f"  {source:25s} {desc}")
        click.echo(f"\nUsage: review-swarm prompt <expert-name>")
        return

    try:
        profile = profiler.load_profile(expert_name)
    except FileNotFoundError:
        click.echo(f"Expert profile not found: {expert_name}", err=True)
        click.echo("Use 'review-swarm prompt --list' to see available profiles.")
        raise SystemExit(1)

    sys_prompt = profile.get("system_prompt", "")
    if not sys_prompt:
        click.echo(f"No system_prompt defined for {expert_name}", err=True)
        raise SystemExit(1)

    click.echo(sys_prompt)


if __name__ == "__main__":
    main()
