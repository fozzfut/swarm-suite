"""MCP Server for FixSwarm -- code fixing tools with KB integration."""

import json
import logging
from typing import Optional
from pathlib import Path
from datetime import datetime, timezone

_log = logging.getLogger("fix_swarm.server")


def create_mcp_server():
    """Create and configure the FixSwarm MCP server."""
    from mcp.server.fastmcp import FastMCP, Context
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
        # Ensure fix sessions dir exists
        fix_dir = Path("~/.swarm-kb/fix/sessions").expanduser()
        fix_dir.mkdir(parents=True, exist_ok=True)
        yield {"fix_sessions_dir": fix_dir}

    def _get_ctx_data(ctx: Optional[Context]) -> dict:
        assert ctx is not None
        return ctx.request_context.lifespan_context

    mcp = FastMCP("FixSwarm", lifespan=lifespan)

    @mcp.tool(
        name="fix_plan",
        description=(
            "Parse a ReviewSwarm report (file path or session ID) and display "
            "the fix plan. Use review_session to read directly from KB."
        ),
    )
    def _fix_plan(
        report: str = "",
        review_session: str = "",
        threshold: str = "medium",
        base_dir: str = ".",
        ctx: Optional[Context] = None,
    ) -> str:
        from .models import Severity
        from .fix_planner import build_plan

        sev = Severity(threshold.lower())
        findings = _load_findings(report, review_session, sev)

        if not findings:
            return json.dumps({"status": "no_findings", "message": "No findings matched threshold"})

        fix_plan = build_plan(findings, base_dir=base_dir)

        if not fix_plan.actions:
            return json.dumps({"status": "no_actions", "message": "No actionable fixes"})

        return json.dumps({
            "findings": len(findings),
            "actions": len(fix_plan.actions),
            "files": fix_plan.files(),
            "plan": fix_plan.to_dict(),
        })

    @mcp.tool(
        name="fix_apply",
        description=(
            "Apply fixes from a ReviewSwarm report. Creates a fix session in KB, "
            "writes cross-references, and marks findings as fixed."
        ),
    )
    def _fix_apply(
        report: str = "",
        review_session: str = "",
        threshold: str = "medium",
        base_dir: str = ".",
        backup: bool = False,
        ctx: Optional[Context] = None,
    ) -> str:
        from .models import Severity
        from .fix_planner import build_plan
        from .fix_applier import apply_plan

        ctx_data = _get_ctx_data(ctx)
        sev = Severity(threshold.lower())
        findings = _load_findings(report, review_session, sev)

        if not findings:
            return json.dumps({"status": "no_findings"})

        fix_plan = build_plan(findings, base_dir=base_dir)

        if not fix_plan.actions:
            return json.dumps({"status": "no_actions"})

        results = apply_plan(fix_plan, base_dir=base_dir, backup=backup)

        ok = sum(1 for r in results if r.success)
        fail = sum(1 for r in results if not r.success)

        # Create fix session in KB
        session_id = _create_fix_session(
            ctx_data["fix_sessions_dir"],
            review_session=review_session,
            report_path=report,
            fix_plan=fix_plan,
            results=results,
        )

        # Write xrefs and mark findings fixed in review session
        if review_session:
            _write_xrefs_and_mark_fixed(session_id, review_session, results)

        return json.dumps({
            "session_id": session_id,
            "succeeded": ok,
            "failed": fail,
            "results": [r.to_dict() for r in results],
        })

    @mcp.tool(
        name="fix_verify",
        description="Verify whether fixes from a report have been applied correctly.",
    )
    def _fix_verify(
        report: str = "",
        review_session: str = "",
        threshold: str = "medium",
        base_dir: str = ".",
        ctx: Optional[Context] = None,
    ) -> str:
        from .models import Severity
        from .fix_planner import build_plan
        from .fix_applier import verify_fixes

        sev = Severity(threshold.lower())
        findings = _load_findings(report, review_session, sev)

        if not findings:
            return json.dumps({"status": "no_findings"})

        fix_plan = build_plan(findings, base_dir=base_dir)

        if not fix_plan.actions:
            return json.dumps({"status": "no_actions"})

        results = verify_fixes(fix_plan, base_dir=base_dir)
        ok = sum(1 for r in results if r.success)
        fail = sum(1 for r in results if not r.success)

        return json.dumps({
            "passed": ok,
            "failed": fail,
            "results": [r.to_dict() for r in results],
        })

    @mcp.tool(
        name="fix_list_sessions",
        description="List all FixSwarm sessions.",
    )
    def _fix_list_sessions(ctx: Optional[Context] = None) -> str:
        ctx_data = _get_ctx_data(ctx)
        fix_dir = ctx_data["fix_sessions_dir"]
        result = []
        if fix_dir.exists():
            for entry in sorted(fix_dir.iterdir()):
                if entry.is_dir():
                    meta_path = entry / "meta.json"
                    if meta_path.exists():
                        try:
                            result.append(json.loads(meta_path.read_text(encoding="utf-8")))
                        except Exception:
                            result.append({"session_id": entry.name})
        return json.dumps(result)

    return mcp


def _load_findings(report: str, review_session: str, threshold):
    """Load findings from either a report file or a review session in KB."""
    if review_session:
        from swarm_kb.finding_reader import get_finding_reader
        reader = get_finding_reader(review_session)
        if not reader.exists():
            return []
        all_findings = reader.search(status="open")
        # Filter by severity threshold
        from .models import Severity, severity_at_least
        return [
            _kb_finding_to_parsed(f) for f in all_findings
            if severity_at_least(Severity(f.get("severity", "medium")), threshold)
        ]
    elif report:
        from .report_parser import parse_report
        return parse_report(report, threshold=threshold)
    return []


def _kb_finding_to_parsed(f: dict):
    """Convert a KB finding dict to a ParsedFinding."""
    from .report_parser import ParsedFinding
    from .models import Severity
    return ParsedFinding(
        id=f["id"],
        file=f["file"],
        line_start=f["line_start"],
        line_end=f["line_end"],
        severity=Severity(f.get("severity", "medium")),
        category=f.get("category", "bug"),
        title=f.get("title", ""),
        actual=f.get("actual", ""),
        expected=f.get("expected", ""),
        suggestion_action=f.get("suggestion_action", "investigate"),
        suggestion_detail=f.get("suggestion_detail", ""),
        snippet=f.get("snippet", ""),
        confidence=f.get("confidence", 0.5),
        status=f.get("status", "open"),
        tags=f.get("tags", []),
    )


def _create_fix_session(fix_dir, review_session, report_path, fix_plan, results) -> str:
    """Create a fix session directory in KB."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    seq = len(list(fix_dir.glob(f"fix-{today}-*"))) + 1
    session_id = f"fix-{today}-{seq:03d}"

    sess_dir = fix_dir / session_id
    sess_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "session_id": session_id,
        "review_session_id": review_session or "",
        "report_path": report_path or "",
        "created_at": now.isoformat(),
        "status": "completed",
        "actions": len(fix_plan.actions),
        "succeeded": sum(1 for r in results if r.success),
        "failed": sum(1 for r in results if not r.success),
    }
    (sess_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (sess_dir / "plan.json").write_text(json.dumps(fix_plan.to_dict(), indent=2), encoding="utf-8")

    results_lines = [json.dumps(r.to_dict()) for r in results]
    (sess_dir / "results.jsonl").write_text("\n".join(results_lines) + "\n", encoding="utf-8")

    return session_id


def _write_xrefs_and_mark_fixed(fix_session_id, review_session_id, results):
    """Write cross-references and mark successful fixes in review findings."""
    try:
        from swarm_kb.config import SuiteConfig
        from swarm_kb.xref import XRefLog
        from swarm_kb.finding_reader import get_finding_reader

        config = SuiteConfig.load()
        xref_log = XRefLog(config.xrefs_path)
        reader = get_finding_reader(review_session_id, config)

        for r in results:
            if r.success:
                xref_log.append(
                    source_tool="fix",
                    source_session=fix_session_id,
                    source_entity_id=r.finding_id,
                    target_tool="review",
                    target_session=review_session_id,
                    target_entity_id=r.finding_id,
                    relation="fixes",
                )
                reader.mark_fixed(r.finding_id, fix_ref=f"fix-session:{fix_session_id}")
    except Exception as exc:
        _log = logging.getLogger("fix_swarm.server")
        _log.warning("Failed to write xrefs/mark fixed: %s", exc)
