"""CLI entry point for monitor-swarm."""

from __future__ import annotations

import json
from pathlib import Path

import click

from swarm_core.logging_setup import setup_logging
from swarm_kb.config import SuiteConfig

from . import __version__


@click.group()
@click.version_option(__version__, prog_name="monitor-swarm")
def main() -> None:
    """monitor-swarm — trace analyzer for instrument software."""
    pass


@main.command()
@click.option("--port", default=8770, help="Port for SSE transport")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--transport", default="sse", type=click.Choice(["sse", "stdio"]))
def serve(port: int, host: str, transport: str) -> None:
    """Start the monitor-swarm MCP server."""
    setup_logging("monitor")
    from .server import create_mcp_server
    mcp = create_mcp_server()
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse", host=host, port=port)


@main.command()
@click.argument("trace_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--spec-constraints", default="[]",
              help="JSON array of spec timing constraints (from spec_get_timing).")
@click.option("--component", default="", help="Component name (e.g. STM32F407VG).")
@click.option("--parser", default="auto",
              type=click.Choice(["auto", "text_log", "saleae_csv"]))
@click.option("--log-pattern", default="",
              help="Custom regex pattern for text logs (named groups: timestamp, message).")
@click.option("--no-persist", is_flag=True, default=False,
              help="Don't write findings into swarm-kb.")
def analyze(trace_path: str, spec_constraints: str, component: str,
            parser: str, log_pattern: str, no_persist: bool) -> None:
    """Analyze a trace file for timing violations against spec constraints."""
    setup_logging("monitor")
    from .detectors import detect_timing_violations, extract_timing_measurements
    from .models import TraceAnalysisResult
    from .parsers import parse_saleae_csv, parse_text_log

    try:
        constraints = json.loads(spec_constraints or "[]")
    except json.JSONDecodeError as exc:
        raise click.UsageError(f"--spec-constraints is not valid JSON: {exc}") from exc

    if parser == "auto":
        parser = "saleae_csv" if trace_path.lower().endswith((".csv", ".tsv")) else "text_log"

    if parser == "text_log":
        events, warnings = parse_text_log(trace_path, log_pattern=log_pattern or None)
    else:
        events, warnings = parse_saleae_csv(trace_path)

    measurements = extract_timing_measurements(events)
    findings = detect_timing_violations(
        measurements, constraints,
        trace_path=trace_path, component_name=component,
    )

    result = TraceAnalysisResult(
        trace_path=trace_path,
        parser=parser,
        events_parsed=len(events),
        measurements_extracted=len(measurements),
        findings=findings,
        parser_warnings=warnings,
    )

    persisted_session: str = ""
    if not no_persist and findings:
        from swarm_core.ids import generate_id
        from swarm_kb.finding_writer import FindingWriter
        from .server import _ensure_session_dir
        config = SuiteConfig.load()
        sid = f"mon-{generate_id('s', length=4)}"
        _ensure_session_dir(config, sid)
        writer = FindingWriter("monitor", sid, config)
        for f in findings:
            writer.post(f.to_finding_dict())
        persisted_session = sid

    out = result.to_dict()
    out["persisted_session_id"] = persisted_session
    click.echo(json.dumps(out, indent=2))


@main.command()
def status() -> None:
    """List monitor sessions and counts."""
    setup_logging("monitor")
    config = SuiteConfig.load()
    sessions_dir = config.tool_sessions_path("monitor")
    if not sessions_dir.is_dir():
        click.echo("No monitor sessions yet.")
        return
    sessions = sorted(p for p in sessions_dir.iterdir() if p.is_dir())
    if not sessions:
        click.echo("No monitor sessions yet.")
        return
    click.echo(f"Monitor sessions ({len(sessions)}):")
    for s in sessions:
        findings = s / "findings.jsonl"
        n = sum(1 for _ in findings.read_text(encoding="utf-8").splitlines()
                if _.strip()) if findings.exists() else 0
        click.echo(f"  {s.name}  -- {n} finding(s)")


if __name__ == "__main__":
    main()
