"""MCP server for monitor-swarm.

Exposes tools that parse a trace, extract timing measurements,
cross-reference against spec-swarm timing constraints (passed in by
the caller — clean layering), and post findings into swarm-kb.

Tools:
- ``monitor_analyze_trace`` — parse + detect + (optionally) persist findings
- ``monitor_list_sessions`` — list existing monitor sessions in the KB
- ``monitor_get_session`` — read findings + meta for a session
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from swarm_core.ids import generate_id
from swarm_core.timeutil import now_iso

from swarm_kb.config import SuiteConfig
from swarm_kb.finding_reader import FindingReader
from swarm_kb.finding_writer import FindingWriter
from swarm_kb.session_meta import list_sessions

from .detectors import detect_timing_violations, extract_timing_measurements
from .models import TraceAnalysisResult
from .parsers import parse_saleae_csv, parse_text_log

_log = logging.getLogger("monitor_swarm.server")


def _ok(payload: dict) -> str:
    return json.dumps({"ok": True, **payload})


def _err(msg: str, **extra) -> str:
    return json.dumps({"ok": False, "error": msg, **extra})


def _detect_parser(trace_path: str) -> str:
    p = trace_path.lower()
    if p.endswith(".csv") or p.endswith(".tsv"):
        return "saleae_csv"
    return "text_log"


def _ensure_session_dir(config: SuiteConfig, session_id: str) -> Path:
    d = config.tool_sessions_path("monitor") / session_id
    d.mkdir(parents=True, exist_ok=True)
    meta_path = d / "meta.json"
    if not meta_path.exists():
        meta_path.write_text(
            json.dumps({
                "session_id": session_id,
                "tool": "monitor",
                "created_at": now_iso(),
            }, indent=2),
            encoding="utf-8",
        )
    return d


def create_mcp_server():
    """Create + configure the monitor-swarm MCP server."""
    from mcp.server.fastmcp import Context, FastMCP

    @dataclass
    class _LifespanState:
        config: SuiteConfig

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[_LifespanState]:
        config = SuiteConfig.load()
        # Ensure the monitor sessions root exists.
        config.tool_sessions_path("monitor").mkdir(parents=True, exist_ok=True)
        yield _LifespanState(config=config)

    def _get_config(ctx: Optional[Context]) -> SuiteConfig:
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context.config

    mcp = FastMCP("MonitorSwarm", lifespan=lifespan)

    # ── monitor_analyze_trace ──────────────────────────────────────────

    @mcp.tool(
        name="monitor_analyze_trace",
        description=(
            "Parse a trace file (text log or Saleae Logic2 CSV), extract timing "
            "measurements, cross-reference against spec-swarm timing "
            "constraints, and emit violation findings. Pass the constraints "
            "as JSON via spec_constraints_json (use spec_get_timing first to "
            "fetch them). parser='auto' picks by file extension. "
            "persist_findings=true writes findings into the KB monitor "
            "session for downstream fix-swarm/review-swarm consumption."
        ),
    )
    def _monitor_analyze_trace(
        trace_path: str,
        spec_constraints_json: str = "[]",
        component_name: str = "",
        parser: str = "auto",
        log_pattern: str = "",
        persist_findings: bool = True,
        session_id: str = "",
        spec_session_id: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)

        if not trace_path:
            return _err("trace_path is required")

        try:
            spec_constraints = json.loads(spec_constraints_json or "[]")
        except json.JSONDecodeError as exc:
            return _err(f"spec_constraints_json is not valid JSON: {exc}")
        if not isinstance(spec_constraints, list):
            return _err("spec_constraints_json must be a JSON array")

        chosen_parser = parser if parser != "auto" else _detect_parser(trace_path)
        if chosen_parser == "text_log":
            events, warnings = parse_text_log(
                trace_path,
                log_pattern=log_pattern or None,
            )
        elif chosen_parser == "saleae_csv":
            events, warnings = parse_saleae_csv(trace_path)
        else:
            return _err(f"Unknown parser: {chosen_parser}")

        measurements = extract_timing_measurements(events)
        findings = detect_timing_violations(
            measurements,
            spec_constraints,
            trace_path=trace_path,
            spec_session_id=spec_session_id,
            component_name=component_name,
        )

        result = TraceAnalysisResult(
            trace_path=trace_path,
            parser=chosen_parser,
            events_parsed=len(events),
            measurements_extracted=len(measurements),
            findings=findings,
            parser_warnings=warnings,
        )

        # Persist findings to swarm-kb monitor sessions if requested.
        persisted_session: str = ""
        if persist_findings and findings:
            sid = session_id or f"mon-{generate_id('s', length=4)}"
            _ensure_session_dir(config, sid)
            writer = FindingWriter("monitor", sid, config)
            for f in findings:
                writer.post(f.to_finding_dict())
            persisted_session = sid

        out = result.to_dict()
        out["persisted_session_id"] = persisted_session
        return _ok(out)

    # ── monitor_list_sessions ──────────────────────────────────────────

    @mcp.tool(
        name="monitor_list_sessions",
        description="List monitor sessions in the KB.",
    )
    def _monitor_list_sessions(ctx: Optional[Context] = None) -> str:
        config = _get_config(ctx)
        try:
            sessions = list_sessions(config, "monitor")
        except Exception as exc:  # noqa: BLE001
            return _err(f"Cannot list monitor sessions: {exc}")
        return _ok({"sessions": sessions})

    # ── monitor_get_session ────────────────────────────────────────────

    @mcp.tool(
        name="monitor_get_session",
        description="Get findings + meta for a monitor session.",
    )
    def _monitor_get_session(
        session_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        if not session_id:
            return _err("session_id is required")
        config = _get_config(ctx)
        session_dir = config.tool_sessions_path("monitor") / session_id
        if not session_dir.is_dir():
            return _err(f"Session not found: {session_id}")
        meta_path = session_dir / "meta.json"
        meta: dict = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
        reader = FindingReader(session_dir)
        findings = reader.read_all() if reader.exists() else []
        return _ok({
            "session_id": session_id,
            "meta": meta,
            "finding_count": len(findings),
            "findings": findings,
        })

    return mcp
