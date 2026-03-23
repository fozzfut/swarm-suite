"""MCP Server for the Swarm knowledge base -- cross-tool tools."""

import json
import logging
from typing import Optional

from .bootstrap import bootstrap
from .config import SuiteConfig, TOOL_NAMES
from .code_map.scanner import scan_project
from .code_map.store import CodeMapStore
from .debate_engine import DebateEngine
from .debate_store import DebateStore
from .decision_store import DecisionStore
from .finding_reader import search_all_findings, get_finding_reader, FindingReader
from .finding_writer import FindingWriter
from .paths import code_map_path, project_hash_for
from .session_meta import count_sessions, list_sessions
from .xref import XRefLog

_log = logging.getLogger("swarm_kb.server")


def create_mcp_server():
    """Create and configure the swarm-kb MCP server."""
    from dataclasses import dataclass as _dataclass
    from mcp.server.fastmcp import FastMCP, Context
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    @_dataclass
    class _LifespanState:
        config: SuiteConfig
        debate_engine: DebateEngine

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[_LifespanState]:
        config = bootstrap()
        engine = DebateEngine(config.debates_path / "active")
        yield _LifespanState(config=config, debate_engine=engine)

    def _get_config(ctx: Optional[Context]) -> SuiteConfig:
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context.config

    def _get_debate_engine(ctx: Optional[Context]) -> DebateEngine:
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context.debate_engine

    mcp = FastMCP("SwarmKB", lifespan=lifespan)

    # ── kb_status ────────────────────────────────────────────────────

    @mcp.tool(
        name="kb_status",
        description=(
            "Get Swarm KB status: session counts per tool, "
            "cross-reference count, decision count, debate count, "
            "storage root path."
        ),
    )
    def _kb_status(ctx: Optional[Context] = None) -> str:
        config = _get_config(ctx)
        counts = count_sessions(config)
        xref_log = XRefLog(config.xrefs_path)
        decision_store = DecisionStore(config.decisions_path / "decisions.jsonl")
        debate_store = DebateStore(config.debates_path / "debates.jsonl")
        engine = _get_debate_engine(ctx)
        return json.dumps({
            "kb_root": str(config.kb_root),
            "sessions": counts,
            "total_sessions": sum(counts.values()),
            "xrefs": xref_log.count(),
            "decision_count": decision_store.count(),
            "debate_count": debate_store.count(),
            "active_debates": engine.count(status="open"),
        }, indent=2)

    # ── kb_scan_project ──────────────────────────────────────────────

    @mcp.tool(
        name="kb_scan_project",
        description=(
            "Scan a project and update its code map. "
            "Returns summary of scanned modules, coupling, complexity. "
            "Use force=true to rescan even if cache is fresh."
        ),
    )
    def _kb_scan_project(
        project_path: str,
        scope: str = "",
        force: bool = False,
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        cm_path = code_map_path(project_path, config)
        store = CodeMapStore(cm_path)

        if not force and store.is_fresh(config.code_map.cache_ttl_hours):
            existing = store.load()
            if existing:
                return json.dumps({
                    "status": "cached",
                    "scanned_at": existing.scanned_at,
                    "total_modules": existing.total_modules,
                    "total_lines": existing.total_lines,
                })

        skip_dirs = set(config.code_map.skip_dirs)
        source_exts = set(config.code_map.source_exts)
        max_size = int(config.code_map.max_file_size_mb * 1024 * 1024)

        code_map = scan_project(
            project_path, scope=scope,
            skip_dirs=skip_dirs, source_exts=source_exts,
            max_file_size=max_size,
        )
        store.save(code_map)

        return json.dumps({
            "status": "scanned",
            "scanned_at": code_map.scanned_at,
            "total_modules": code_map.total_modules,
            "total_lines": code_map.total_lines,
            "coupling_count": len(code_map.coupling),
        })

    # ── kb_get_code_map ──────────────────────────────────────────────

    @mcp.tool(
        name="kb_get_code_map",
        description=(
            "Get the cached code map for a project. "
            "Returns modules, dependency graph, coupling metrics, complexity. "
            "Run kb_scan_project first if no cache exists."
        ),
    )
    def _kb_get_code_map(
        project_path: str,
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        cm_path = code_map_path(project_path, config)
        store = CodeMapStore(cm_path)
        code_map = store.load()

        if code_map is None:
            return json.dumps({"error": "No code map found. Run kb_scan_project first."})

        return json.dumps(code_map.to_dict())

    # ── kb_list_sessions ─────────────────────────────────────────────

    @mcp.tool(
        name="kb_list_sessions",
        description=(
            "List sessions across all tools (or filter by tool). "
            "Returns session IDs, status, timestamps."
        ),
    )
    def _kb_list_sessions(
        tool: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        sessions = list_sessions(config, tool=tool or None)
        return json.dumps(sessions, default=str)

    # ── kb_get_xrefs ─────────────────────────────────────────────────

    @mcp.tool(
        name="kb_get_xrefs",
        description=(
            "Get cross-tool references. Filter by source_tool, target_tool, "
            "source_session, target_session, target_entity_id, relation."
        ),
    )
    def _kb_get_xrefs(
        source_tool: str = "",
        target_tool: str = "",
        source_session: str = "",
        target_session: str = "",
        target_entity_id: str = "",
        relation: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        xref_log = XRefLog(config.xrefs_path)
        xrefs = xref_log.query(
            source_tool=source_tool or None,
            target_tool=target_tool or None,
            source_session=source_session or None,
            target_session=target_session or None,
            target_entity_id=target_entity_id or None,
            relation=relation or None,
        )
        return json.dumps([x.to_dict() for x in xrefs])

    # ── kb_post_xref ─────────────────────────────────────────────────

    @mcp.tool(
        name="kb_post_xref",
        description=(
            "Create a cross-reference between sessions/entities. "
            "Relations: fixes, documents, addresses, informed_by."
        ),
    )
    def _kb_post_xref(
        source_tool: str,
        source_session: str,
        source_entity_id: str,
        target_tool: str,
        target_session: str,
        target_entity_id: str,
        relation: str,
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        xref_log = XRefLog(config.xrefs_path)
        xref = xref_log.append(
            source_tool=source_tool,
            source_session=source_session,
            source_entity_id=source_entity_id,
            target_tool=target_tool,
            target_session=target_session,
            target_entity_id=target_entity_id,
            relation=relation,
        )
        return json.dumps(xref.to_dict())

    # ── kb_search_findings ───────────────────────────────────────────

    @mcp.tool(
        name="kb_search_findings",
        description=(
            "Search findings across sessions. "
            "Filter by tool (default: all tools), file, severity, "
            "status, min_confidence."
        ),
    )
    def _kb_search_findings(
        tool: str = "",
        file: str = "",
        severity: str = "",
        status: str = "",
        min_confidence: float = 0.0,
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)

        # Determine which tools to search
        if tool:
            tools_to_search = [tool]
        else:
            tools_to_search = list(TOOL_NAMES)

        all_results: list[dict] = []
        for t in tools_to_search:
            sessions_dir = config.tool_sessions_path(t)
            if not sessions_dir.exists():
                continue
            for entry in sorted(sessions_dir.iterdir()):
                if not entry.is_dir():
                    continue
                reader = FindingReader(entry)
                if not reader.exists():
                    continue
                findings = reader.search(
                    file=file or None,
                    severity=severity or None,
                    status=status or None,
                    min_confidence=min_confidence if min_confidence > 0 else None,
                )
                for f in findings:
                    f["_tool"] = t
                    f["_session_id"] = entry.name
                all_results.extend(findings)

        return json.dumps(all_results)

    # ── kb_post_finding ──────────────────────────────────────────────

    @mcp.tool(
        name="kb_post_finding",
        description="Post a finding from any tool into shared KB storage.",
    )
    def _kb_post_finding(
        tool: str,
        session_id: str,
        finding: str,
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        try:
            finding_data = json.loads(finding)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid JSON in finding: {exc}"})

        writer = FindingWriter(tool, session_id, config)
        finding_id = writer.post(finding_data)

        # Return the posted finding with assigned ID
        finding_data["id"] = finding_id
        return json.dumps({"status": "posted", "finding": finding_data})

    # ── kb_post_decision ─────────────────────────────────────────────

    @mcp.tool(
        name="kb_post_decision",
        description="Record an architectural decision (ADR).",
    )
    def _kb_post_decision(
        title: str,
        status: str = "accepted",
        rationale: str = "",
        context: str = "",
        consequences: str = "",
        source_tool: str = "",
        source_session: str = "",
        debate_id: str = "",
        project_path: str = "",
        tags: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        store = DecisionStore(config.decisions_path / "decisions.jsonl")

        # Parse comma-separated strings into lists
        consequences_list: list[str] = []
        if consequences:
            try:
                consequences_list = json.loads(consequences)
            except json.JSONDecodeError:
                consequences_list = [c.strip() for c in consequences.split(",") if c.strip()]

        tags_list: list[str] = []
        if tags:
            try:
                tags_list = json.loads(tags)
            except json.JSONDecodeError:
                tags_list = [t.strip() for t in tags.split(",") if t.strip()]

        decision = store.append(
            title=title,
            status=status,
            rationale=rationale,
            context=context,
            consequences=consequences_list,
            source_tool=source_tool,
            source_session=source_session,
            debate_id=debate_id,
            project_path=project_path,
            tags=tags_list,
        )
        return json.dumps(decision.to_dict())

    # ── kb_get_decisions ─────────────────────────────────────────────

    @mcp.tool(
        name="kb_get_decisions",
        description="Query architectural decisions.",
    )
    def _kb_get_decisions(
        status: str = "",
        source_tool: str = "",
        tag: str = "",
        project_path: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        store = DecisionStore(config.decisions_path / "decisions.jsonl")
        decisions = store.query(
            status=status,
            source_tool=source_tool,
            tag=tag,
            project_path=project_path,
        )
        return json.dumps([d.to_dict() for d in decisions])

    # ── kb_update_decision_status ────────────────────────────────────

    @mcp.tool(
        name="kb_update_decision_status",
        description="Update a decision's status.",
    )
    def _kb_update_decision_status(
        decision_id: str,
        new_status: str,
        superseded_by: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        store = DecisionStore(config.decisions_path / "decisions.jsonl")
        updated = store.update_status(decision_id, new_status, superseded_by=superseded_by)
        if updated:
            decision = store.get_by_id(decision_id)
            return json.dumps({
                "status": "updated",
                "decision": decision.to_dict() if decision else None,
            })
        return json.dumps({"status": "not_found", "decision_id": decision_id})

    # ── kb_post_debate ───────────────────────────────────────────────

    @mcp.tool(
        name="kb_post_debate",
        description="Record a debate result in shared KB.",
    )
    def _kb_post_debate(
        topic: str,
        source_tool: str,
        source_session: str = "",
        project_path: str = "",
        status: str = "resolved",
        proposals: str = "",
        winning_proposal: str = "",
        decision_id: str = "",
        participant_count: int = 0,
        vote_tally: str = "",
        tags: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        store = DebateStore(config.debates_path / "debates.jsonl")

        # Parse JSON strings into structured data
        proposals_list: list[dict] = []
        if proposals:
            try:
                proposals_list = json.loads(proposals)
            except json.JSONDecodeError:
                proposals_list = []

        vote_tally_dict: dict = {}
        if vote_tally:
            try:
                vote_tally_dict = json.loads(vote_tally)
            except json.JSONDecodeError:
                vote_tally_dict = {}

        tags_list: list[str] = []
        if tags:
            try:
                tags_list = json.loads(tags)
            except json.JSONDecodeError:
                tags_list = [t.strip() for t in tags.split(",") if t.strip()]

        record = store.append(
            topic=topic,
            source_tool=source_tool,
            source_session=source_session,
            project_path=project_path,
            status=status,
            proposals=proposals_list,
            winning_proposal=winning_proposal,
            decision_id=decision_id,
            participant_count=participant_count,
            vote_tally=vote_tally_dict,
            tags=tags_list,
        )
        return json.dumps(record.to_dict())

    # ── kb_get_debates ───────────────────────────────────────────────

    @mcp.tool(
        name="kb_get_debates",
        description="Query debates.",
    )
    def _kb_get_debates(
        status: str = "",
        source_tool: str = "",
        project_path: str = "",
        tag: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        store = DebateStore(config.debates_path / "debates.jsonl")
        debates = store.query(
            status=status,
            source_tool=source_tool,
            project_path=project_path,
            tag=tag,
        )
        return json.dumps([d.to_dict() for d in debates])

    # ── kb_start_debate ──────────────────────────────────────────────

    @mcp.tool(
        name="kb_start_debate",
        description="Start a new debate. Any tool can initiate.",
    )
    def _kb_start_debate(
        topic: str,
        context: str = "",
        project_path: str = "",
        source_tool: str = "",
        source_session: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            engine = _get_debate_engine(ctx)
            debate = engine.start_debate(
                topic=topic,
                context=context,
                project_path=project_path,
                source_tool=source_tool,
                source_session=source_session,
            )
            return json.dumps(debate.to_dict())
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── kb_propose ───────────────────────────────────────────────────

    @mcp.tool(
        name="kb_propose",
        description="Submit a proposal to an open debate.",
    )
    def _kb_propose(
        debate_id: str,
        author: str,
        title: str,
        description: str,
        pros: str = "",
        cons: str = "",
        trade_offs: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            engine = _get_debate_engine(ctx)

            pros_list: list[str] = []
            if pros:
                try:
                    pros_list = json.loads(pros)
                except json.JSONDecodeError:
                    pros_list = [p.strip() for p in pros.split(",") if p.strip()]

            cons_list: list[str] = []
            if cons:
                try:
                    cons_list = json.loads(cons)
                except json.JSONDecodeError:
                    cons_list = [c.strip() for c in cons.split(",") if c.strip()]

            trade_offs_list: list[str] = []
            if trade_offs:
                try:
                    trade_offs_list = json.loads(trade_offs)
                except json.JSONDecodeError:
                    trade_offs_list = [t.strip() for t in trade_offs.split(",") if t.strip()]

            proposal_id = engine.propose(
                debate_id=debate_id,
                author=author,
                title=title,
                description=description,
                pros=pros_list,
                cons=cons_list,
                trade_offs=trade_offs_list,
            )
            return json.dumps({"proposal_id": proposal_id, "debate_id": debate_id})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── kb_critique ──────────────────────────────────────────────────

    @mcp.tool(
        name="kb_critique",
        description="Critique an existing proposal in a debate.",
    )
    def _kb_critique(
        debate_id: str,
        proposal_id: str,
        critic: str,
        verdict: str,
        reasoning: str,
        suggested_changes: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            engine = _get_debate_engine(ctx)

            changes_list: list[str] = []
            if suggested_changes:
                try:
                    changes_list = json.loads(suggested_changes)
                except json.JSONDecodeError:
                    changes_list = [c.strip() for c in suggested_changes.split(",") if c.strip()]

            critique_id = engine.critique(
                debate_id=debate_id,
                proposal_id=proposal_id,
                critic=critic,
                verdict=verdict,
                reasoning=reasoning,
                suggested_changes=changes_list,
            )
            return json.dumps({"critique_id": critique_id, "debate_id": debate_id})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── kb_vote ──────────────────────────────────────────────────────

    @mcp.tool(
        name="kb_vote",
        description="Vote on a proposal in a debate.",
    )
    def _kb_vote(
        debate_id: str,
        agent: str,
        proposal_id: str,
        support: bool = True,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            engine = _get_debate_engine(ctx)
            engine.vote(
                debate_id=debate_id,
                agent=agent,
                proposal_id=proposal_id,
                support=support,
            )
            return json.dumps({
                "status": "voted",
                "debate_id": debate_id,
                "agent": agent,
                "proposal_id": proposal_id,
                "support": support,
            })
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── kb_resolve_debate ────────────────────────────────────────────

    @mcp.tool(
        name="kb_resolve_debate",
        description=(
            "Resolve a debate: tally votes, pick winner, generate decision. "
            "Also auto-posts the decision to the DecisionStore."
        ),
    )
    def _kb_resolve_debate(
        debate_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            engine = _get_debate_engine(ctx)
            result = engine.resolve(debate_id)

            # Auto-post the decision to DecisionStore
            decision_data = result.get("decision", {})
            if decision_data and decision_data.get("status") == "accepted":
                config = _get_config(ctx)
                dec_store = DecisionStore(config.decisions_path / "decisions.jsonl")
                debate = engine.get_debate(debate_id)
                dec_record = dec_store.append(
                    title=decision_data.get("title", ""),
                    status="accepted",
                    rationale=decision_data.get("rationale", ""),
                    context=debate.context if debate else "",
                    debate_id=debate_id,
                    source_tool=debate.source_tool if debate else "",
                    source_session=debate.source_session if debate else "",
                    project_path=debate.project_path if debate else "",
                )
                result["decision_record_id"] = dec_record.id

            return json.dumps(result)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── kb_get_debate ────────────────────────────────────────────────

    @mcp.tool(
        name="kb_get_debate",
        description=(
            "Get full debate state including proposals, critiques, votes."
        ),
    )
    def _kb_get_debate(
        debate_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            engine = _get_debate_engine(ctx)
            debate = engine.get_debate(debate_id)
            if debate is None:
                return json.dumps({"error": f"Debate {debate_id!r} not found"})
            return json.dumps(debate.to_dict())
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── kb_get_transcript ────────────────────────────────────────────

    @mcp.tool(
        name="kb_get_transcript",
        description="Get markdown transcript of a debate.",
    )
    def _kb_get_transcript(
        debate_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            engine = _get_debate_engine(ctx)
            transcript = engine.get_transcript(debate_id)
            return transcript
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── kb_cancel_debate ─────────────────────────────────────────────

    @mcp.tool(
        name="kb_cancel_debate",
        description="Cancel an open debate.",
    )
    def _kb_cancel_debate(
        debate_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            engine = _get_debate_engine(ctx)
            engine.cancel(debate_id)
            return json.dumps({"status": "cancelled", "debate_id": debate_id})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── kb_migrate ───────────────────────────────────────────────────

    @mcp.tool(
        name="kb_migrate",
        description=(
            "Manually trigger migration from legacy storage paths "
            "(~/.review-swarm, ~/.doc-swarm) to the shared KB. "
            "Idempotent -- skips already-migrated sessions."
        ),
    )
    def _kb_migrate(ctx: Optional[Context] = None) -> str:
        from .compat import migrate_all
        config = _get_config(ctx)
        result = migrate_all(config)
        total = sum(len(v) for v in result.values())
        return json.dumps({
            "migrated": result,
            "total": total,
        })

    return mcp
