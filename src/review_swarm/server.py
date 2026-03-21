"""MCP Server with 24 tool handlers, MCP Resources, subscriptions, event bus, and agent messaging."""

from __future__ import annotations

from dataclasses import dataclass, field
from .config import Config
from .rate_limiter import RateLimiter
from .session_manager import SessionManager
from .expert_profiler import ExpertProfiler
from .orchestrator import Orchestrator
from .report_generator import ReportGenerator
from .models import (
    Finding, Reaction, Severity, Category, Action, ReactionType, EventType,
    Message, MessageType, Status, now_iso,
)


@dataclass
class AppContext:
    session_manager: SessionManager
    expert_profiler: ExpertProfiler
    orchestrator: Orchestrator
    config: Config
    finding_limiter: RateLimiter = field(default_factory=RateLimiter)
    message_limiter: RateLimiter = field(default_factory=RateLimiter)
    # Maps resource URI string -> set of MCP session objects (for push notifications)
    resource_subscriptions: dict[str, set] = field(default_factory=dict)


def create_app_context(
    config: Config | None = None,
    project_path_override: str | None = None,
) -> AppContext:
    from .logging_config import setup_logging
    setup_logging()

    if config is None:
        config = Config.load()
    config.sessions_path.mkdir(parents=True, exist_ok=True)

    custom_dirs = []
    if config.custom_experts_path.exists():
        custom_dirs.append(config.custom_experts_path)

    profiler = ExpertProfiler(custom_dirs=custom_dirs)
    mgr = SessionManager(config, expert_profiler=profiler)
    return AppContext(
        session_manager=mgr,
        expert_profiler=profiler,
        orchestrator=Orchestrator(config, mgr, profiler),
        config=config,
        finding_limiter=RateLimiter(
            max_calls=config.rate_limit.max_findings_per_minute,
            window_seconds=60,
        ),
        message_limiter=RateLimiter(
            max_calls=config.rate_limit.max_messages_per_minute,
            window_seconds=60,
        ),
    )


# --- Tool handler functions (called by MCP server or tests directly) ---
# These remain synchronous and pure -- no event publishing here.
# Event publishing happens in the async MCP wrappers below.

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
    result = claim.to_dict()
    return result


def tool_release_file(
    ctx: AppContext, session_id: str, file: str, expert_role: str,
) -> dict:
    reg = ctx.session_manager.get_claim_registry(session_id)
    reg.release(session_id, file, expert_role)
    result = {"status": "released", "file": file, "expert_role": expert_role}
    return result


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
    ctx.finding_limiter.check(f"{session_id}:{expert_role}")
    # Validate file path: must be relative, no traversal, no backslashes
    if file.startswith('/') or file.startswith('\\') or '..' in file.split('/'):
        raise ValueError(f"Invalid file path: {file!r}. Must be relative, no traversal.")
    if '\\' in file:
        raise ValueError(f"Invalid file path: {file!r}. Must be relative, no traversal.")
    if not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be 0.0-1.0, got {confidence}")
    if line_start < 0 or line_end < 0:
        raise ValueError(f"line numbers must be >= 0, got start={line_start}, end={line_end}")
    if line_end < line_start:
        raise ValueError(f"line_end ({line_end}) must be >= line_start ({line_start})")

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
    limit: int = 0,
    offset: int = 0,
) -> list[dict]:
    store = ctx.session_manager.get_finding_store(session_id)
    return [f.to_dict() for f in store.get(
        severity=severity, category=category, status=status,
        file=file, expert_role=expert_role, min_confidence=min_confidence,
        limit=limit, offset=offset,
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
    result = updated.to_dict()
    return result


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


def tool_orchestrate_review(
    ctx: AppContext,
    project_path: str,
    scope: str = "",
    task: str = "",
    max_experts: int = 5,
    session_name: str | None = None,
) -> dict:
    """Create a complete review plan and return it as structured JSON.

    The calling LLM follows the returned phases step by step.
    """
    plan = ctx.orchestrator.plan_review(
        project_path=project_path,
        scope=scope,
        task=task,
        max_experts=max_experts,
        session_name=session_name,
    )
    return plan.to_dict()


def tool_find_duplicates(
    ctx: AppContext,
    session_id: str,
    file: str,
    line_start: int,
    line_end: int,
    title: str,
) -> list[dict]:
    """Check for potential duplicate findings before posting."""
    store = ctx.session_manager.get_finding_store(session_id)
    dupes = store.find_duplicates(file, line_start, line_end, title)
    return [{"id": d.id, "title": d.title, "expert_role": d.expert_role,
             "file": d.file, "line_start": d.line_start, "line_end": d.line_end,
             "severity": d.severity.value} for d in dupes]


def tool_mark_fixed(
    ctx: AppContext,
    session_id: str,
    finding_id: str,
    fix_ref: str = "",
) -> dict:
    """Mark a finding as FIXED. Called by fix-agents after applying a patch.

    Args:
        finding_id: The finding to mark as fixed.
        fix_ref: Optional reference to the fix (commit hash, PR url, etc.)
    """
    store = ctx.session_manager.get_finding_store(session_id)
    finding = store.get_by_id(finding_id)
    if finding is None:
        raise KeyError(f"Finding {finding_id} not found")
    store.update_status(finding_id, Status.FIXED)
    if fix_ref:
        store.add_comment(finding_id, {
            "expert_role": "_system",
            "content": f"Marked as FIXED. Ref: {fix_ref}",
            "created_at": now_iso(),
        })
    updated = store.get_by_id(finding_id)
    result = updated.to_dict() if updated else {"id": finding_id, "status": "fixed"}
    try:
        bus = ctx.session_manager.get_event_bus(session_id)
        bus.publish_sync(EventType.STATUS_CHANGED, {
            "finding_id": finding_id,
            "old_status": finding.status.value,
            "new_status": "fixed",
            "fix_ref": fix_ref,
        })
    except (KeyError, Exception):
        pass
    return result


def tool_bulk_update_status(
    ctx: AppContext,
    session_id: str,
    finding_ids: list[str],
    new_status: str,
    reason: str = "",
) -> dict:
    """Update status of multiple findings at once.

    Args:
        finding_ids: List of finding IDs to update.
        new_status: New status (fixed, wontfix, open, confirmed, disputed).
        reason: Optional reason for the status change.
    """
    status = Status(new_status)
    store = ctx.session_manager.get_finding_store(session_id)
    updated = 0
    errors = []
    for fid in finding_ids:
        try:
            store.update_status(fid, status)
            if reason:
                store.add_comment(fid, {
                    "expert_role": "_system",
                    "content": f"Status → {new_status}: {reason}",
                    "created_at": now_iso(),
                })
            updated += 1
        except KeyError:
            errors.append(fid)
    return {
        "updated": updated,
        "errors": errors,
        "new_status": new_status,
    }


def tool_post_findings_batch(
    ctx: AppContext,
    session_id: str,
    findings: list[dict],
) -> list[dict]:
    """Post multiple findings in one call. Returns list of results."""
    results = []
    for f in findings:
        try:
            result = tool_post_finding(
                ctx, session_id,
                expert_role=f["expert_role"],
                file=f["file"],
                line_start=f["line_start"],
                line_end=f["line_end"],
                severity=f["severity"],
                category=f["category"],
                title=f["title"],
                actual=f["actual"],
                expected=f["expected"],
                source_ref=f["source_ref"],
                suggestion_action=f["suggestion_action"],
                suggestion_detail=f["suggestion_detail"],
                confidence=f["confidence"],
                snippet=f.get("snippet", ""),
                tags=f.get("tags"),
                related_findings=f.get("related_findings"),
                agent_id=f.get("agent_id", "unknown"),
            )
            results.append(result)
        except (ValueError, KeyError) as exc:
            results.append({"error": str(exc), "title": f.get("title", "unknown")})
    return results


def tool_post_comment(
    ctx: AppContext,
    session_id: str,
    finding_id: str,
    expert_role: str,
    content: str,
) -> dict:
    """Post an inline comment on a finding."""
    store = ctx.session_manager.get_finding_store(session_id)
    comment = {
        "expert_role": expert_role,
        "content": content,
        "created_at": now_iso(),
    }
    store.add_comment(finding_id, comment)
    finding = store.get_by_id(finding_id)
    return finding.to_dict() if finding else {"error": "finding not found"}


def tool_get_events(
    ctx: AppContext,
    session_id: str,
    since: str | None = None,
    event_type: str | None = None,
) -> list[dict]:
    """Get session events since a timestamp (polling fallback)."""
    bus = ctx.session_manager.get_event_bus(session_id)
    et = EventType(event_type) if event_type else None
    return bus.get_events(since=since, event_type=et)


def tool_send_message(
    ctx: AppContext,
    session_id: str,
    from_agent: str,
    to_agent: str,
    content: str,
    message_type: str = "direct",
    in_reply_to: str = "",
    urgent: bool = False,
    context: dict | None = None,
) -> dict:
    """Send a message to another agent or broadcast to all.

    context dict can include finding/file references:
      {"finding_id": "f-abc", "file": "src/x.py", "line_start": 42,
       "line_end": 58, "title": "Race condition"}
    """
    ctx.message_limiter.check(f"{session_id}:{from_agent}")
    mbus = ctx.session_manager.get_message_bus(session_id)
    mbus.register_agent(from_agent)

    mt = MessageType(message_type)
    msg = Message(
        id=Message.generate_id(),
        session_id=session_id,
        from_agent=from_agent,
        to_agent=to_agent,
        message_type=mt,
        content=content,
        in_reply_to=in_reply_to,
        urgent=urgent if mt != MessageType.QUERY else True,
        context=context or {},
    )
    mbus.send(msg)

    result = msg.to_dict()
    return result


def tool_mark_phase_done(
    ctx: AppContext, session_id: str, expert_role: str, phase: int,
) -> dict:
    """Mark that an agent has completed a phase. Returns barrier status."""
    barrier = ctx.session_manager.get_phase_barrier(session_id)
    barrier.register_agent(expert_role)
    return barrier.mark_phase_done(expert_role, phase)


def tool_check_phase_ready(
    ctx: AppContext, session_id: str, phase: int,
) -> dict:
    """Check if a phase can be started (all agents done with previous phase)."""
    barrier = ctx.session_manager.get_phase_barrier(session_id)
    return barrier.check_phase_ready(phase)


def tool_get_phase_status(ctx: AppContext, session_id: str) -> dict:
    """Get full phase status for all agents."""
    barrier = ctx.session_manager.get_phase_barrier(session_id)
    return barrier.get_status()


def tool_get_inbox(
    ctx: AppContext,
    session_id: str,
    expert_role: str,
    since: str | None = None,
    message_type: str | None = None,
) -> list[dict]:
    """Get messages for a specific agent (their inbox)."""
    mbus = ctx.session_manager.get_message_bus(session_id)
    mbus.register_agent(expert_role)
    return mbus.get_inbox(expert_role, since=since, message_type=message_type)


def tool_get_thread(
    ctx: AppContext,
    session_id: str,
    message_id: str,
) -> list[dict]:
    """Get a query and all its responses."""
    mbus = ctx.session_manager.get_message_bus(session_id)
    return mbus.get_thread(message_id)


def tool_broadcast(
    ctx: AppContext,
    session_id: str,
    from_agent: str,
    content: str,
) -> dict:
    """Broadcast a message to all agents in the session."""
    mbus = ctx.session_manager.get_message_bus(session_id)
    mbus.register_agent(from_agent)
    msg = mbus.send_broadcast(session_id, from_agent, content)
    return msg.to_dict()


# --- MCP Server wiring ---

def _inject_pending(app: AppContext, session_id: str, expert_role: str, result: dict) -> dict:
    """Inject _pending notifications into a tool response dict.

    This is the key to parallel agent coordination:
    every tool response includes pending messages so agents
    react immediately without explicit polling.
    """
    try:
        mbus = app.session_manager.get_message_bus(session_id)
        mbus.register_agent(expert_role)
        pending = mbus.get_pending(expert_role)
        if pending:
            result["_pending"] = pending
    except KeyError:
        pass  # session may not exist yet or be ended
    return result


async def _notify_resource_subscribers(
    app: AppContext, session_id: str, resource_type: str,
) -> None:
    """Notify all MCP subscribers that a resource has been updated."""
    uri_str = f"reviewswarm://sessions/{session_id}/{resource_type}"
    sessions = app.resource_subscriptions.get(uri_str, set())
    if not sessions:
        return

    stale = set()
    for mcp_session in sessions:
        try:
            await mcp_session.send_resource_updated(uri_str)
        except Exception:
            stale.add(mcp_session)
    for s in stale:
        sessions.discard(s)


def create_mcp_server():
    """Create and configure the MCP server with all 21 tools + resources."""
    from mcp.server.fastmcp import FastMCP, Context
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
        ctx = create_app_context()
        yield ctx

    mcp = FastMCP("ReviewSwarm", lifespan=lifespan)

    # ── Orchestrator ─────────────────────────────────────────────────

    @mcp.tool(
        name="orchestrate_review",
        description=(
            "One-command review: provide scope and task, get a complete "
            "execution plan with session, experts, file assignments, and "
            "phased instructions. Follow the returned phases step by step. "
            "Example: orchestrate_review(project_path='.', scope='src/', task='security audit')"
        ),
    )
    def _orchestrate_review(
        project_path: str,
        scope: str = "",
        task: str = "",
        max_experts: int = 5,
        session_name: str = "",
        # ctx default is None per FastMCP convention; framework injects the real value
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_orchestrate_review(
            app, project_path, scope=scope, task=task,
            max_experts=max_experts,
            session_name=session_name or None,
        )
        return json.dumps(result, ensure_ascii=False)

    # ── Session Management Tools ─────────────────────────────────────

    @mcp.tool(name="start_session", description="Start a new collaborative review session for a project")
    def _start_session(project_path: str, name: str = "", ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_start_session(app, project_path, name=name or None)
        return json.dumps(result)

    @mcp.tool(name="end_session", description="End a review session and generate the final report")
    async def _end_session(session_id: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        bus = app.session_manager.get_event_bus(session_id)
        result = tool_end_session(app, session_id)  # clears caches
        await bus.publish(EventType.SESSION_ENDED, result)
        # Don't notify subscribers after session is ended -- caches are cleared
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

    # ── Expert Coordination Tools ────────────────────────────────────

    @mcp.tool(name="suggest_experts", description="Analyze the project and recommend expert profiles")
    def _suggest_experts(session_id: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_suggest_experts(app, session_id)
        return json.dumps(result)

    @mcp.tool(name="claim_file", description="Claim a file for review")
    async def _claim_file(session_id: str, file: str, expert_role: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        agent_id = _resolve_agent_id(ctx, expert_role)
        result = tool_claim_file(app, session_id, file, expert_role, agent_id=agent_id)

        bus = app.session_manager.get_event_bus(session_id)
        await bus.publish(EventType.FILE_CLAIMED, result)
        await _notify_resource_subscribers(app, session_id, "claims")
        await _notify_resource_subscribers(app, session_id, "events")

        _inject_pending(app, session_id, expert_role, result)
        return json.dumps(result)

    @mcp.tool(name="release_file", description="Release a previously claimed file")
    async def _release_file(session_id: str, file: str, expert_role: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_release_file(app, session_id, file, expert_role)

        bus = app.session_manager.get_event_bus(session_id)
        await bus.publish(EventType.FILE_RELEASED, {
            "file": file, "expert_role": expert_role, **result,
        })
        await _notify_resource_subscribers(app, session_id, "claims")
        await _notify_resource_subscribers(app, session_id, "events")

        _inject_pending(app, session_id, expert_role, result)
        return json.dumps(result)

    @mcp.tool(name="get_claims", description="See which files are currently claimed")
    def _get_claims(session_id: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_get_claims(app, session_id)
        return json.dumps(result)

    # ── Finding Tools ────────────────────────────────────────────────

    @mcp.tool(
        name="post_finding",
        description="Post a review finding. MUST include evidence (actual + expected + source_ref).",
    )
    async def _post_finding(
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

        bus = app.session_manager.get_event_bus(session_id)
        await bus.publish(EventType.FINDING_POSTED, result)
        await _notify_resource_subscribers(app, session_id, "findings")
        await _notify_resource_subscribers(app, session_id, "events")

        _inject_pending(app, session_id, expert_role, result)
        return json.dumps(result)

    @mcp.tool(name="get_findings", description="Get findings from the shared board. Supports pagination (limit/offset). Pass caller_role to get pending messages.")
    def _get_findings(
        session_id: str,
        file: str = "", severity: str = "", category: str = "",
        expert_role: str = "", status: str = "",
        min_confidence: float = 0.0,
        limit: int = 0, offset: int = 0,
        caller_role: str = "",
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
            limit=limit, offset=offset,
        )
        # Wrap list result with pending notifications
        if caller_role:
            wrapper = {"findings": result}
            _inject_pending(app, session_id, caller_role, wrapper)
            return json.dumps(wrapper)
        return json.dumps(result)

    @mcp.tool(name="react", description="React to another expert's finding")
    async def _react(
        session_id: str, expert_role: str, finding_id: str,
        reaction: str, reason: str,
        related_finding_id: str = "",
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        agent_id = _resolve_agent_id(ctx, expert_role)

        # Capture old status to detect status changes
        store = app.session_manager.get_finding_store(session_id)
        old_finding = store.get_by_id(finding_id)
        old_status = old_finding.status.value if old_finding else None

        result = tool_react(
            app, session_id, expert_role, finding_id, reaction, reason,
            related_finding_id=related_finding_id, agent_id=agent_id,
        )

        bus = app.session_manager.get_event_bus(session_id)
        await bus.publish(EventType.REACTION_ADDED, result)

        # Publish STATUS_CHANGED if status transitioned
        new_status = result.get("status")
        if old_status and new_status and old_status != new_status:
            await bus.publish(EventType.STATUS_CHANGED, {
                "finding_id": finding_id,
                "old_status": old_status,
                "new_status": new_status,
            })

        await _notify_resource_subscribers(app, session_id, "findings")
        await _notify_resource_subscribers(app, session_id, "events")

        _inject_pending(app, session_id, expert_role, result)
        return json.dumps(result)

    @mcp.tool(name="get_summary", description="Get aggregated summary report")
    def _get_summary(session_id: str, format: str = "markdown", ctx: Context = None) -> str:
        app = ctx.request_context.lifespan_context
        return tool_get_summary(app, session_id, fmt=format or None)

    # ── Duplicate Detection & Batch Tools ───────────────────────────

    @mcp.tool(
        name="find_duplicates",
        description="Check for potential duplicate findings before posting. Returns similar findings by file, line overlap, and title.",
    )
    def _find_duplicates(
        session_id: str, file: str, line_start: int, line_end: int, title: str,
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_find_duplicates(app, session_id, file, line_start, line_end, title)
        return json.dumps(result)

    @mcp.tool(
        name="post_findings_batch",
        description="Post multiple findings in one call. Each finding in the array needs the same fields as post_finding.",
    )
    async def _post_findings_batch(
        session_id: str, findings: list[dict],
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        results = tool_post_findings_batch(app, session_id, findings)

        bus = app.session_manager.get_event_bus(session_id)
        for r in results:
            if "error" not in r:
                await bus.publish(EventType.FINDING_POSTED, r)
        await _notify_resource_subscribers(app, session_id, "findings")
        await _notify_resource_subscribers(app, session_id, "events")

        return json.dumps({"posted": len([r for r in results if "error" not in r]),
                           "errors": len([r for r in results if "error" in r]),
                           "results": results})

    # ── Comments Tool ─────────────────────────────────────────────────

    @mcp.tool(
        name="post_comment",
        description="Post an inline comment on a finding. For discussion, questions, or additional context.",
    )
    def _post_comment(
        session_id: str, finding_id: str, expert_role: str, content: str,
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_post_comment(app, session_id, finding_id, expert_role, content)
        return json.dumps(result)

    # ── Status Update Tools (for fix-agents) ───────────────────────

    @mcp.tool(
        name="mark_fixed",
        description=(
            "Mark a finding as FIXED after applying a fix. "
            "Optionally attach a fix_ref (commit hash, PR URL). "
            "Called by fix-agents after patching code."
        ),
    )
    def _mark_fixed(
        session_id: str, finding_id: str, fix_ref: str = "",
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_mark_fixed(app, session_id, finding_id, fix_ref=fix_ref)
        return json.dumps(result)

    @mcp.tool(
        name="bulk_update_status",
        description=(
            "Update status of multiple findings at once. "
            "Statuses: fixed, wontfix, open, confirmed, disputed. "
            "Use after batch-fixing bugs from the review report."
        ),
    )
    def _bulk_update_status(
        session_id: str, finding_ids: list[str], new_status: str,
        reason: str = "",
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_bulk_update_status(
            app, session_id, finding_ids, new_status, reason=reason,
        )
        return json.dumps(result)

    # ── Event Polling Tool ───────────────────────────────────────────

    @mcp.tool(
        name="get_events",
        description=(
            "Get real-time session events since a timestamp. "
            "Types: finding_posted, reaction_added, status_changed, "
            "file_claimed, file_released, session_ended. "
            "Polling fallback for clients without MCP resource subscriptions."
        ),
    )
    def _get_events(
        session_id: str, since: str = "", event_type: str = "",
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_get_events(
            app, session_id,
            since=since or None,
            event_type=event_type or None,
        )
        return json.dumps(result)

    # ── Phase Barrier Tools (two-pass sync) ────────────────────────

    @mcp.tool(
        name="mark_phase_done",
        description=(
            "Mark that you (as expert_role) have completed a phase. "
            "Phase 1 = review (post findings), Phase 2 = cross-check (react to others). "
            "Returns whether all agents are done and who is still working."
        ),
    )
    def _mark_phase_done(
        session_id: str, expert_role: str, phase: int,
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_mark_phase_done(app, session_id, expert_role, phase)
        _inject_pending(app, session_id, expert_role, result)
        return json.dumps(result)

    @mcp.tool(
        name="check_phase_ready",
        description=(
            "Check if a phase can be started. Phase 2 is ready only when ALL "
            "agents have completed Phase 1. Returns ready status and who is still working."
        ),
    )
    def _check_phase_ready(
        session_id: str, phase: int,
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        return json.dumps(tool_check_phase_ready(app, session_id, phase))

    @mcp.tool(
        name="get_phase_status",
        description="Get full phase completion status for all agents in the session.",
    )
    def _get_phase_status(session_id: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        return json.dumps(tool_get_phase_status(app, session_id))

    # ── Agent Messaging Tools (star topology) ──────────────────────

    @mcp.tool(
        name="send_message",
        description=(
            "Send a message to another agent (direct), all agents (broadcast), "
            "ask a question (query), or reply to a query (response). "
            "Types: direct, broadcast, query, response. "
            "Use context to attach finding/file references: "
            '{"finding_id": "f-abc", "file": "src/x.py", "line_start": 42, "title": "..."}. '
            "Queries are always urgent. Set urgent=true for direct/broadcast to interrupt agents."
        ),
    )
    async def _send_message(
        session_id: str, from_agent: str, content: str,
        to_agent: str = "*", message_type: str = "direct",
        in_reply_to: str = "",
        urgent: bool = False,
        context: dict | None = None,
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_send_message(
            app, session_id, from_agent, to_agent, content,
            message_type=message_type, in_reply_to=in_reply_to,
            urgent=urgent, context=context,
        )

        bus = app.session_manager.get_event_bus(session_id)
        et = EventType.BROADCAST if message_type == "broadcast" else EventType.MESSAGE
        await bus.publish(et, result)
        await _notify_resource_subscribers(app, session_id, "messages")
        await _notify_resource_subscribers(app, session_id, "events")

        _inject_pending(app, session_id, from_agent, result)
        return json.dumps(result)

    @mcp.tool(
        name="get_inbox",
        description=(
            "Get messages for this agent. Returns direct messages, broadcasts, "
            "queries from other agents, and responses to your queries. "
            "Filter by since (ISO timestamp) or message_type."
        ),
    )
    def _get_inbox(
        session_id: str, expert_role: str,
        since: str = "", message_type: str = "",
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_get_inbox(
            app, session_id, expert_role,
            since=since or None,
            message_type=message_type or None,
        )
        return json.dumps(result)

    @mcp.tool(
        name="get_thread",
        description="Get a query message and all its responses (conversation thread).",
    )
    def _get_thread(session_id: str, message_id: str, ctx: Context = None) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_get_thread(app, session_id, message_id)
        return json.dumps(result)

    @mcp.tool(
        name="broadcast",
        description=(
            "Broadcast a message to ALL agents in the session. "
            "Use for announcements, work splitting proposals, or status updates."
        ),
    )
    async def _broadcast(
        session_id: str, from_agent: str, content: str,
        ctx: Context = None,
    ) -> str:
        import json
        app = ctx.request_context.lifespan_context
        result = tool_broadcast(app, session_id, from_agent, content)

        bus = app.session_manager.get_event_bus(session_id)
        await bus.publish(EventType.BROADCAST, result)
        await _notify_resource_subscribers(app, session_id, "messages")
        await _notify_resource_subscribers(app, session_id, "events")

        return json.dumps(result)

    # ── MCP Subscription Handlers ────────────────────────────────────

    try:
        # Access the low-level server for subscription handler registration
        low_level = getattr(mcp, '_mcp_server', None)
        if low_level is not None:
            @low_level.subscribe_resource()
            async def _on_subscribe(uri) -> None:
                uri_str = str(uri)
                try:
                    request_ctx = low_level.request_context
                    session = request_ctx.session
                    app = request_ctx.lifespan_context
                    if uri_str not in app.resource_subscriptions:
                        app.resource_subscriptions[uri_str] = set()
                    app.resource_subscriptions[uri_str].add(session)
                except Exception:
                    pass

            @low_level.unsubscribe_resource()
            async def _on_unsubscribe(uri) -> None:
                uri_str = str(uri)
                try:
                    request_ctx = low_level.request_context
                    session = request_ctx.session
                    app = request_ctx.lifespan_context
                    if uri_str in app.resource_subscriptions:
                        app.resource_subscriptions[uri_str].discard(session)
                except Exception:
                    pass
    except Exception:
        pass  # Subscription handlers are optional; server works without them

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
