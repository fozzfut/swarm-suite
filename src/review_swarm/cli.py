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


@main.command()
@click.argument("project_path", default=".")
@click.option("--scope", default="", help="File pattern or subdirectory (e.g., src/, **/*.py)")
@click.option("--task", default="", help="Review focus (e.g., security audit, pre-release)")
@click.option("--experts", "max_experts", default=5, help="Max number of experts")
@click.option("--name", default="", help="Session name")
def review(project_path: str, scope: str, task: str, max_experts: int, name: str):
    """One-command review: plan and print execution instructions."""
    import json
    config = Config.load()
    from .session_manager import SessionManager
    from .expert_profiler import ExpertProfiler
    from .orchestrator import Orchestrator

    profiler = ExpertProfiler()
    mgr = SessionManager(config, expert_profiler=profiler)
    orch = Orchestrator(config, mgr, profiler)

    plan = orch.plan_review(
        project_path=str(Path(project_path).resolve()),
        scope=scope,
        task=task,
        max_experts=max_experts,
        session_name=name or None,
    )

    click.echo(f"\n{plan.summary}\n")
    click.echo("=" * 60)
    for phase in plan.phases:
        click.echo(f"\n## Phase {phase['phase']}: {phase['name']}")
        click.echo(f"   {phase['description']}\n")
        for instr in phase["instructions"]:
            expert = instr.get("expert_role", "")
            prefix = f"   [{expert}]" if expert else "   "
            click.echo(f"{prefix} {instr['description']}")
            if instr.get("files"):
                file_count = len(instr["files"])
                preview = instr["files"][:5]
                click.echo(f"   Files ({file_count}): {', '.join(preview)}{'...' if file_count > 5 else ''}")
    click.echo(f"\n{'=' * 60}")
    click.echo(f"Session ID: {plan.session_id}")
    click.echo(f"Use this session ID with MCP tools or: review-swarm report {plan.session_id}")


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


@main.command()
@click.argument("session_id")
@click.option("--interval", default=2.0, help="Poll interval in seconds")
def tail(session_id: str, interval: float):
    """Live-monitor a session's events as they happen."""
    import json
    import time

    config = Config.load()
    from .session_manager import SessionManager

    mgr = SessionManager(config)
    try:
        mgr.get_project_path(session_id)
    except KeyError:
        click.echo(f"Session not found: {session_id}", err=True)
        raise SystemExit(1)

    click.echo(f"Tailing {session_id} (Ctrl+C to stop)...\n")
    watermark = ""
    try:
        while True:
            bus = mgr.get_event_bus(session_id)
            events = bus.get_events(since=watermark or None)
            for ev in events:
                ts = ev["timestamp"][:19]
                etype = ev["event_type"]
                payload = ev.get("payload", {})

                if etype == "finding_posted":
                    sev = payload.get("severity", "?")
                    title = payload.get("title", "?")
                    expert = payload.get("expert_role", "?")
                    click.echo(f"  [{ts}] FINDING [{sev.upper()}] {title} (by {expert})")
                elif etype == "reaction_added":
                    reaction = payload.get("reactions", [{}])[-1] if payload.get("reactions") else {}
                    rtype = reaction.get("reaction", "?")
                    expert = reaction.get("expert_role", payload.get("expert_role", "?"))
                    click.echo(f"  [{ts}] REACTION {rtype} (by {expert})")
                elif etype == "status_changed":
                    fid = payload.get("finding_id", "?")
                    old = payload.get("old_status", "?")
                    new = payload.get("new_status", "?")
                    click.echo(f"  [{ts}] STATUS {fid}: {old} -> {new}")
                elif etype == "file_claimed":
                    f = payload.get("file", "?")
                    expert = payload.get("expert_role", "?")
                    click.echo(f"  [{ts}] CLAIM {f} (by {expert})")
                elif etype == "file_released":
                    f = payload.get("file", "?")
                    click.echo(f"  [{ts}] RELEASE {f}")
                elif etype == "session_ended":
                    click.echo(f"  [{ts}] SESSION ENDED")
                    return
                elif etype in ("message", "broadcast"):
                    fr = payload.get("from_agent", "?")
                    content = payload.get("content", "")[:80]
                    click.echo(f"  [{ts}] MSG from {fr}: {content}")
                else:
                    click.echo(f"  [{ts}] {etype}")

                watermark = ev["timestamp"]
            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("\nStopped.")


@main.command()
@click.argument("session_id", required=False)
def stats(session_id: str | None):
    """Show aggregate statistics for a session or all sessions."""
    import json
    from collections import Counter

    config = Config.load()
    from .session_manager import SessionManager

    mgr = SessionManager(config)
    sessions = mgr.list_sessions()

    if not sessions:
        click.echo("No sessions found.")
        return

    if session_id:
        try:
            info = mgr.get_session(session_id)
        except KeyError:
            click.echo(f"Session not found: {session_id}", err=True)
            raise SystemExit(1)

        click.echo(f"Session: {session_id}")
        click.echo(f"  Status:   {info.get('status')}")
        click.echo(f"  Findings: {info.get('finding_count', 0)}")
        click.echo(f"  Claims:   {info.get('active_claims', 0)}")
        by_sev = info.get("findings_by_severity", {})
        if by_sev:
            parts = [f"{v} {k}" for k, v in sorted(by_sev.items())]
            click.echo(f"  By severity: {', '.join(parts)}")
        by_status = info.get("findings_by_status", {})
        if by_status:
            parts = [f"{v} {k}" for k, v in sorted(by_status.items())]
            click.echo(f"  By status:   {', '.join(parts)}")

        # Expert breakdown
        store = mgr.get_finding_store(session_id)
        findings = store.get()
        experts: Counter = Counter()
        for f in findings:
            experts[f.expert_role] += 1
        if experts:
            click.echo("  By expert:")
            for expert, count in experts.most_common():
                click.echo(f"    {expert:25s} {count} findings")
    else:
        # Aggregate across all sessions
        total_findings = 0
        total_sessions = len(sessions)
        by_status: Counter = Counter()
        for s in sessions:
            by_status[s.get("status", "unknown")] += 1

        click.echo(f"Total sessions: {total_sessions}")
        for status, count in by_status.most_common():
            click.echo(f"  {status}: {count}")

        active = [s for s in sessions if s.get("status") == "active"]
        if active:
            click.echo(f"\nActive sessions:")
            for s in active:
                click.echo(f"  {s['session_id']}  {s.get('name', '')}")


@main.command()
@click.argument("session_id")
@click.option("--output", "-o", default="-", help="Output file (- for stdout)")
@click.option("--format", "fmt", default="markdown", type=click.Choice(["markdown", "json", "sarif"]))
def export(session_id: str, output: str, fmt: str):
    """Export a session report to a file."""
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

    if fmt == "sarif":
        content = gen.generate_sarif(session_id)
    else:
        content = gen.generate(session_id, fmt=fmt)

    if output == "-":
        click.echo(content)
    else:
        Path(output).write_text(content, encoding="utf-8")
        click.echo(f"Exported to {output}")


@main.command()
@click.argument("session_a")
@click.argument("session_b")
def diff(session_a: str, session_b: str):
    """Compare findings between two sessions."""
    config = Config.load()
    from .session_manager import SessionManager

    mgr = SessionManager(config)

    try:
        store_a = mgr.get_finding_store(session_a)
        store_b = mgr.get_finding_store(session_b)
    except KeyError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)

    findings_a = {(f.file, f.title): f for f in store_a.get()}
    findings_b = {(f.file, f.title): f for f in store_b.get()}

    keys_a = set(findings_a.keys())
    keys_b = set(findings_b.keys())

    only_a = keys_a - keys_b
    only_b = keys_b - keys_a
    common = keys_a & keys_b

    click.echo(f"Comparing {session_a} vs {session_b}\n")
    click.echo(f"  {session_a}: {len(findings_a)} findings")
    click.echo(f"  {session_b}: {len(findings_b)} findings")
    click.echo(f"  Common: {len(common)}, Only in A: {len(only_a)}, Only in B: {len(only_b)}\n")

    if only_a:
        click.echo(f"Only in {session_a}:")
        for file, title in sorted(only_a):
            f = findings_a[(file, title)]
            click.echo(f"  - [{f.severity.value.upper()}] {title} ({file})")

    if only_b:
        click.echo(f"\nOnly in {session_b}:")
        for file, title in sorted(only_b):
            f = findings_b[(file, title)]
            click.echo(f"  + [{f.severity.value.upper()}] {title} ({file})")

    # Status changes in common findings
    changed = []
    for key in sorted(common):
        fa, fb = findings_a[key], findings_b[key]
        if fa.status != fb.status or fa.severity != fb.severity:
            changed.append((key, fa, fb))

    if changed:
        click.echo(f"\nChanged findings:")
        for (file, title), fa, fb in changed:
            parts = []
            if fa.severity != fb.severity:
                parts.append(f"severity: {fa.severity.value} -> {fb.severity.value}")
            if fa.status != fb.status:
                parts.append(f"status: {fa.status.value} -> {fb.status.value}")
            click.echo(f"  ~ {title} ({file}): {', '.join(parts)}")


if __name__ == "__main__":
    main()
