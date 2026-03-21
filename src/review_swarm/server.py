"""MCP Server with 12 tool handlers and lifespan context."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .session_manager import SessionManager
from .expert_profiler import ExpertProfiler
from .report_generator import ReportGenerator
from .models import Finding, Reaction, Severity, Category, Action, ReactionType


@dataclass
class AppContext:
    session_manager: SessionManager
    expert_profiler: ExpertProfiler
    config: Config


def create_app_context(
    config: Config | None = None,
    project_path_override: str | None = None,
) -> AppContext:
    if config is None:
        config = Config.load()
    config.sessions_path.mkdir(parents=True, exist_ok=True)

    custom_dirs = []
    if config.custom_experts_path.exists():
        custom_dirs.append(config.custom_experts_path)

    profiler = ExpertProfiler(custom_dirs=custom_dirs)
    return AppContext(
        session_manager=SessionManager(config, expert_profiler=profiler),
        expert_profiler=profiler,
        config=config,
    )


# --- Tool handler functions (called by MCP server or tests directly) ---

def tool_start_session(ctx: AppContext, project_path: str, name: str | None = None) -> dict:
    sid = ctx.session_manager.start_session(project_path, name=name)
    return {"session_id": sid, "status": "active"}


def tool_end_session(ctx: AppContext, session_id: str) -> dict:
    return ctx.session_manager.end_session(session_id)


def tool_get_session(ctx: AppContext, session_id: str) -> dict:
    return ctx.session_manager.get_session(session_id)


def tool_list_sessions(ctx: AppContext) -> list[dict]:
    return ctx.session_manager.list_sessions()


def tool_suggest_experts(ctx: AppContext, session_id: str) -> list[dict]:
    project_path = ctx.session_manager.get_project_path(session_id)
    return ctx.expert_profiler.suggest_experts(project_path)


def tool_claim_file(
    ctx: AppContext, session_id: str, file: str, expert_role: str,
    agent_id: str = "unknown",
) -> dict:
    reg = ctx.session_manager.get_claim_registry(session_id)
    claim = reg.claim(session_id, file, expert_role, agent_id)
    return claim.to_dict()


def tool_release_file(
    ctx: AppContext, session_id: str, file: str, expert_role: str,
) -> dict:
    reg = ctx.session_manager.get_claim_registry(session_id)
    reg.release(session_id, file, expert_role)
    return {"status": "released"}


def tool_get_claims(ctx: AppContext, session_id: str) -> list[dict]:
    reg = ctx.session_manager.get_claim_registry(session_id)
    return [c.to_dict() for c in reg.get_claims(session_id)]


def tool_post_finding(
    ctx: AppContext,
    session_id: str,
    expert_role: str,
    file: str,
    line_start: int,
    line_end: int,
    severity: str,
    category: str,
    title: str,
    actual: str,
    expected: str,
    source_ref: str,
    suggestion_action: str,
    suggestion_detail: str,
    confidence: float,
    snippet: str = "",
    tags: list[str] | None = None,
    related_findings: list[str] | None = None,
    agent_id: str = "unknown",
) -> dict:
    store = ctx.session_manager.get_finding_store(session_id)
    finding = Finding(
        id=Finding.generate_id(),
        session_id=session_id,
        expert_role=expert_role,
        agent_id=agent_id,
        file=file,
        line_start=line_start,
        line_end=line_end,
        snippet=snippet,
        severity=Severity(severity),
        category=Category(category),
        title=title,
        actual=actual,
        expected=expected,
        source_ref=source_ref,
        suggestion_action=Action(suggestion_action),
        suggestion_detail=suggestion_detail,
        confidence=confidence,
        tags=tags or [],
        related_findings=related_findings or [],
    )
    store.post(finding)
    result = finding.to_dict()
    dupes = store.find_duplicates(
        file, line_start, line_end, title, exclude_id=finding.id,
    )
    if dupes:
        result["potential_duplicates"] = [
            {"id": d.id, "title": d.title, "expert_role": d.expert_role}
            for d in dupes
        ]
    return result


def tool_get_findings(
    ctx: AppContext,
    session_id: str,
    *,
    severity: str | None = None,
    category: str | None = None,
    status: str | None = None,
    file: str | None = None,
    expert_role: str | None = None,
    min_confidence: float | None = None,
) -> list[dict]:
    store = ctx.session_manager.get_finding_store(session_id)
    return [f.to_dict() for f in store.get(
        severity=severity, category=category, status=status,
        file=file, expert_role=expert_role, min_confidence=min_confidence,
    )]


def tool_react(
    ctx: AppContext,
    session_id: str,
    expert_role: str,
    finding_id: str,
    reaction: str,
    reason: str,
    related_finding_id: str = "",
    agent_id: str = "unknown",
) -> dict:
    engine = ctx.session_manager.get_reaction_engine(session_id)
    r = Reaction(
        session_id=session_id,
        finding_id=finding_id,
        agent_id=agent_id,
        expert_role=expert_role,
        reaction=ReactionType(reaction),
        reason=reason,
        related_finding_id=related_finding_id,
    )
    updated = engine.react(r)
    return updated.to_dict()


def tool_get_summary(
    ctx: AppContext, session_id: str, fmt: str | None = None,
) -> str:
    """Generate summary report.

    The MCP schema exposes this as 'format'; internally we use 'fmt'
    to avoid shadowing the Python builtin format().
    """
    effective_fmt = fmt or ctx.config.default_format
    store = ctx.session_manager.get_finding_store(session_id)
    gen = ReportGenerator(store)
    return gen.generate(session_id, fmt=effective_fmt)


# --- MCP Server wiring ---

def create_mcp_server():
    """Create and configure the MCP server with all 12 tools."""
    from mcp.server.mcpserver import MCPServer, Context
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    @asynccontextmanager
    async def lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
        ctx = create_app_context()
        yield ctx

    mcp = MCPServer("ReviewSwarm", lifespan=lifespan)

    @mcp.tool(name="start_session", description="Start a new collaborative review session for a project")
    def _start_session(project_path: str, name: str = "", ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_start_session(app, project_path, name=name or None)
        return json.dumps(result)

    @mcp.tool(name="end_session", description="End a review session and generate the final report")
    def _end_session(session_id: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_end_session(app, session_id)
        return json.dumps(result)

    @mcp.tool(name="get_session", description="Get current session state")
    def _get_session(session_id: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_get_session(app, session_id)
        return json.dumps(result)

    @mcp.tool(name="list_sessions", description="List all review sessions")
    def _list_sessions(ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_list_sessions(app)
        return json.dumps(result)

    @mcp.tool(name="suggest_experts", description="Analyze the project and recommend expert profiles")
    def _suggest_experts(session_id: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_suggest_experts(app, session_id)
        return json.dumps(result)

    @mcp.tool(name="claim_file", description="Claim a file for review")
    def _claim_file(session_id: str, file: str, expert_role: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        agent_id = _resolve_agent_id(ctx, expert_role)
        result = tool_claim_file(app, session_id, file, expert_role, agent_id=agent_id)
        return json.dumps(result)

    @mcp.tool(name="release_file", description="Release a previously claimed file")
    def _release_file(session_id: str, file: str, expert_role: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_release_file(app, session_id, file, expert_role)
        return json.dumps(result)

    @mcp.tool(name="get_claims", description="See which files are currently claimed")
    def _get_claims(session_id: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_get_claims(app, session_id)
        return json.dumps(result)

    @mcp.tool(
        name="post_finding",
        description="Post a review finding. MUST include evidence (actual + expected + source_ref).",
    )
    def _post_finding(
        session_id: str, expert_role: str,
        file: str, line_start: int, line_end: int,
        severity: str, category: str, title: str,
        actual: str, expected: str, source_ref: str,
        suggestion_action: str, suggestion_detail: str,
        confidence: float,
        snippet: str = "", tags: list[str] | None = None, related_findings: list[str] | None = None,
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        agent_id = _resolve_agent_id(ctx, expert_role)
        result = tool_post_finding(
            app, session_id, expert_role, file, line_start, line_end,
            severity, category, title, actual, expected, source_ref,
            suggestion_action, suggestion_detail, confidence,
            snippet=snippet, tags=tags or [], related_findings=related_findings or [],
            agent_id=agent_id,
        )
        return json.dumps(result)

    @mcp.tool(name="get_findings", description="Get findings from the shared board")
    def _get_findings(
        session_id: str,
        file: str = "", severity: str = "", category: str = "",
        expert_role: str = "", status: str = "",
        min_confidence: float = 0.0,
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_get_findings(
            app, session_id,
            severity=severity or None, category=category or None,
            status=status or None, file=file or None,
            expert_role=expert_role or None,
            min_confidence=min_confidence if min_confidence > 0 else None,
        )
        return json.dumps(result)

    @mcp.tool(name="react", description="React to another expert's finding")
    def _react(
        session_id: str, expert_role: str, finding_id: str,
        reaction: str, reason: str,
        related_finding_id: str = "",
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        agent_id = _resolve_agent_id(ctx, expert_role)
        result = tool_react(
            app, session_id, expert_role, finding_id, reaction, reason,
            related_finding_id=related_finding_id, agent_id=agent_id,
        )
        return json.dumps(result)

    @mcp.tool(name="get_summary", description="Get aggregated summary report")
    def _get_summary(session_id: str, format: str = "markdown", ctx: Context = None) -> str:
        app = ctx.request_context.lifespan_context
        return tool_get_summary(app, session_id, fmt=format or None)

    return mcp


def _resolve_agent_id(ctx, expert_role: str) -> str:
    """Auto-generate agent_id from MCP connection context + expert_role.
    Uses request_id as a stable per-connection identifier."""
    try:
        rid = ctx.request_id or "unknown"
        conn_id = str(rid)[:8]
    except Exception:
        conn_id = "unknown"
    return f"{conn_id}-{expert_role}"
