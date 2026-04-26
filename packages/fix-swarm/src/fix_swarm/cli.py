"""CLI entry point for FixSwarm."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import __version__
from .fix_applier import apply_plan, verify_fixes
from .fix_planner import build_plan
from .models import FixPlan, Severity
from .report_parser import parse_report


SEVERITY_NAMES = [s.value for s in Severity]


@click.group()
@click.version_option(__version__, prog_name="fix-swarm")
def main() -> None:
    """FixSwarm -- Multi-agent code fixer for ReviewSwarm reports."""


@main.command()
@click.option("--port", default=8791, help="Port for SSE transport")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--transport", default="sse", type=click.Choice(["sse", "stdio"]))
def serve(port: int, host: str, transport: str) -> None:
    """Start the FixSwarm MCP server."""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    from .server import create_mcp_server

    mcp = create_mcp_server()
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse", host=host, port=port)


@main.command()
@click.argument("report", type=click.Path(exists=True))
@click.option(
    "--threshold",
    type=click.Choice(SEVERITY_NAMES, case_sensitive=False),
    default="medium",
    help="Minimum severity to include (default: medium).",
)
@click.option("--dry-run", is_flag=True, help="Show plan without applying fixes.")
@click.option(
    "--base-dir",
    type=click.Path(exists=True, file_okay=False),
    default=".",
    help="Base directory for resolving file paths in findings.",
)
def plan(report: str, threshold: str, dry_run: bool, base_dir: str) -> None:
    """Parse a ReviewSwarm report and display the fix plan."""
    sev = Severity(threshold.lower())
    findings = parse_report(report, threshold=sev)
    if not findings:
        click.echo("No findings matched the severity threshold.")
        return

    click.echo(f"Parsed {len(findings)} finding(s) at severity >= {sev.value}\n")

    fix_plan = build_plan(findings, base_dir=base_dir)

    if not fix_plan.actions:
        click.echo("No actionable fixes (only 'fix' suggestions generate actions).")
        return

    click.echo(f"Fix plan: {len(fix_plan.actions)} action(s) across {len(fix_plan.files())} file(s)\n")
    for action in fix_plan.actions:
        click.echo(f"  [{action.action.value.upper()}] {action.file}:{action.line_start}-{action.line_end}")
        click.echo(f"    Finding: {action.finding_id}")
        click.echo(f"    Rationale: {action.rationale}")
        if action.action.value == "replace":
            click.echo(f"    Old: {_truncate(action.old_text)}")
            click.echo(f"    New: {_truncate(action.new_text)}")
        elif action.action.value == "insert":
            click.echo(f"    Insert: {_truncate(action.new_text)}")
        click.echo()

    if dry_run:
        click.echo("(dry-run -- no files modified)")
        # Also compute diffs for display
        results = apply_plan(fix_plan, base_dir=base_dir, dry_run=True)
        for r in results:
            if r.diff:
                click.echo(r.diff)


@main.command()
@click.argument("report", type=click.Path(exists=True))
@click.option(
    "--threshold",
    type=click.Choice(SEVERITY_NAMES, case_sensitive=False),
    default="medium",
    help="Minimum severity to include (default: medium).",
)
@click.option("--backup", is_flag=True, help="Create .bak backup before modifying files.")
@click.option(
    "--base-dir",
    type=click.Path(exists=True, file_okay=False),
    default=".",
    help="Base directory for resolving file paths in findings.",
)
def apply(report: str, threshold: str, backup: bool, base_dir: str) -> None:
    """Parse a ReviewSwarm report and apply fixes to source files."""
    sev = Severity(threshold.lower())
    findings = parse_report(report, threshold=sev)
    if not findings:
        click.echo("No findings matched the severity threshold.")
        return

    fix_plan = build_plan(findings, base_dir=base_dir)

    if not fix_plan.actions:
        click.echo("No actionable fixes to apply.")
        return

    click.echo(f"Applying {len(fix_plan.actions)} fix(es) across {len(fix_plan.files())} file(s)...")
    results = apply_plan(fix_plan, base_dir=base_dir, backup=backup)

    ok = sum(1 for r in results if r.success)
    fail = sum(1 for r in results if not r.success)
    click.echo(f"\nDone: {ok} succeeded, {fail} failed.")

    for r in results:
        status = "OK" if r.success else "FAIL"
        click.echo(f"  [{status}] {r.finding_id}" + (f"  -- {r.error}" if r.error else ""))

    if fail:
        sys.exit(1)


@main.command()
@click.argument("report", type=click.Path(exists=True))
@click.option(
    "--threshold",
    type=click.Choice(SEVERITY_NAMES, case_sensitive=False),
    default="medium",
    help="Minimum severity to include (default: medium).",
)
@click.option(
    "--base-dir",
    type=click.Path(exists=True, file_okay=False),
    default=".",
    help="Base directory for resolving file paths in findings.",
)
def verify(report: str, threshold: str, base_dir: str) -> None:
    """Check whether fixes from a report have been applied correctly."""
    sev = Severity(threshold.lower())
    findings = parse_report(report, threshold=sev)
    if not findings:
        click.echo("No findings matched the severity threshold.")
        return

    fix_plan = build_plan(findings, base_dir=base_dir)

    if not fix_plan.actions:
        click.echo("No actionable fixes to verify.")
        return

    results = verify_fixes(fix_plan, base_dir=base_dir)
    ok = sum(1 for r in results if r.success)
    fail = sum(1 for r in results if not r.success)
    click.echo(f"Verification: {ok} passed, {fail} failed out of {len(results)} fix(es).")

    for r in results:
        status = "PASS" if r.success else "FAIL"
        click.echo(f"  [{status}] {r.finding_id}" + (f"  -- {r.error}" if r.error else ""))

    if fail:
        sys.exit(1)


def _truncate(text: str, max_len: int = 80) -> str:
    """Truncate text for display, replacing newlines with spaces."""
    flat = text.replace("\n", " ").strip()
    if len(flat) > max_len:
        return flat[: max_len - 3] + "..."
    return flat


@main.command()
@click.argument("expert_name", required=False)
@click.option("--list", "list_all", is_flag=True, help="List available fix experts")
def prompt(expert_name: str | None, list_all: bool) -> None:
    """Print the composed system prompt for a fix expert (role + skills)."""
    from pathlib import Path
    from swarm_core.experts import ExpertRegistry, NullSuggestStrategy

    builtin = Path(__file__).parent / "experts"
    reg = ExpertRegistry(builtin_dir=builtin, suggest_strategy=NullSuggestStrategy())

    if list_all or expert_name is None:
        click.echo("Available fix expert profiles:\n")
        for p in sorted(reg.list_profiles(), key=lambda x: x.slug):
            click.echo(f"  {p.slug:25s} {p.description}")
        click.echo("\nUsage: fix-swarm prompt <expert-name>")
        return

    try:
        profile = reg.load_profile(expert_name)
    except FileNotFoundError:
        click.echo(f"Expert profile not found: {expert_name}", err=True)
        click.echo("Use 'fix-swarm prompt --list' to see available profiles.")
        raise SystemExit(1)

    if not profile.system_prompt:
        click.echo(f"No system_prompt defined for {expert_name}", err=True)
        raise SystemExit(1)

    # composed_system_prompt = role + uses_skills + universal skills
    click.echo(profile.composed_system_prompt)
