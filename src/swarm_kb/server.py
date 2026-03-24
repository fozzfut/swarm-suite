"""MCP Server for the Swarm knowledge base -- cross-tool tools."""

import json
import logging
from pathlib import Path
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
from .pipeline import PipelineManager, STAGE_INFO, STAGE_ORDER
from .quality_gate import (
    GateThresholds, RoundMetrics,
    compute_round_metrics, check_gate,
    load_thresholds, save_thresholds,
)
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
        pipeline_manager: PipelineManager
        decision_store: DecisionStore
        debate_store: DebateStore

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[_LifespanState]:
        config = bootstrap()
        engine = DebateEngine(config.debates_path / "active")
        pipe_mgr = PipelineManager(config.pipelines_path)
        dec_store = DecisionStore(config.decisions_path / "decisions.jsonl")
        dbt_store = DebateStore(config.debates_path / "debates.jsonl")
        yield _LifespanState(
            config=config,
            debate_engine=engine,
            pipeline_manager=pipe_mgr,
            decision_store=dec_store,
            debate_store=dbt_store,
        )

    def _get_config(ctx: Optional[Context]) -> SuiteConfig:
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context.config

    def _get_debate_engine(ctx: Optional[Context]) -> DebateEngine:
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context.debate_engine

    def _get_pipeline_manager(ctx: Optional[Context]) -> PipelineManager:
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context.pipeline_manager

    def _get_decision_store(ctx: Optional[Context]) -> DecisionStore:
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context.decision_store

    def _get_debate_store(ctx: Optional[Context]) -> DebateStore:
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context.debate_store

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
        decision_store = _get_decision_store(ctx)
        debate_store = _get_debate_store(ctx)
        engine = _get_debate_engine(ctx)
        pipe_mgr = _get_pipeline_manager(ctx)
        pipelines = pipe_mgr.list_all()
        active_pipelines = [p for p in pipelines if p.stages.get(p.current_stage) and p.stages[p.current_stage].status == "active"]
        return json.dumps({
            "kb_root": str(config.kb_root),
            "sessions": counts,
            "total_sessions": sum(counts.values()),
            "xrefs": xref_log.count(),
            "decision_count": decision_store.count(),
            "debate_count": debate_store.count(),
            "active_debates": engine.count(status="open"),
            "pipeline_count": len(pipelines),
            "active_pipelines": len(active_pipelines),
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
        store = _get_decision_store(ctx)

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
        store = _get_decision_store(ctx)
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
        store = _get_decision_store(ctx)
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
        store = _get_debate_store(ctx)

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
        store = _get_debate_store(ctx)
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
                dec_store = _get_decision_store(ctx)
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

    # ── kb_start_pipeline ─────────────────────────────────────────────

    @mcp.tool(
        name="kb_start_pipeline",
        description=(
            "Start a new analysis pipeline for a project. "
            "Set include_spec=True for embedded/hardware projects "
            "to begin with datasheet/spec analysis before architecture."
        ),
    )
    def _kb_start_pipeline(
        project_path: str,
        include_spec: bool = False,
        ctx: Optional[Context] = None,
    ) -> str:
        pipe_mgr = _get_pipeline_manager(ctx)
        pipe = pipe_mgr.start(project_path)

        # If not embedded/hardware project, skip spec stage
        if not include_spec:
            pipe_mgr.skip_to(pipe.id, "arch")
        pipe = pipe_mgr.get(pipe.id)  # re-fetch after potential skip

        first_stage = pipe.current_stage
        info = STAGE_INFO[first_stage]
        msg = ("Pipeline started. Begin with hardware spec analysis."
               if first_stage == "spec"
               else "Pipeline started. Begin with architecture analysis.")
        return json.dumps({
            "pipeline_id": pipe.id,
            "current_stage": first_stage,
            "stage_name": info["name"],
            "message": msg,
            "actions": info["actions"],
            "pipeline": pipe.to_dict(),
        }, indent=2)

    # ── kb_pipeline_status ─────────────────────────────────────────

    @mcp.tool(
        name="kb_pipeline_status",
        description=(
            "Get current pipeline status: which stage, "
            "what's been done, what's next."
        ),
    )
    def _kb_pipeline_status(
        pipeline_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        pipe_mgr = _get_pipeline_manager(ctx)
        pipe = pipe_mgr.get(pipeline_id)
        if pipe is None:
            return json.dumps({"error": f"Pipeline {pipeline_id} not found"})

        current = pipe.get_current()
        info = STAGE_INFO[pipe.current_stage]
        current_idx = STAGE_ORDER.index(pipe.current_stage)

        completed = [s for s in STAGE_ORDER if pipe.stages[s].status == "completed"]
        remaining = STAGE_ORDER[current_idx + 1:]

        return json.dumps({
            "pipeline_id": pipe.id,
            "project_path": pipe.project_path,
            "current_stage": pipe.current_stage,
            "stage_name": info["name"],
            "stage_status": current.status,
            "completed_stages": completed,
            "remaining_stages": remaining,
            "actions": info["actions"],
            "stage_stats": {
                "session_ids": current.session_ids,
                "approved_findings": current.approved_findings,
                "dismissed_findings": current.dismissed_findings,
            },
            "pipeline": pipe.to_dict(),
        }, indent=2)

    # ── kb_advance_pipeline ────────────────────────────────────────

    @mcp.tool(
        name="kb_advance_pipeline",
        description=(
            "User gate: advance pipeline to the next stage. "
            "Call after reviewing current stage results."
        ),
    )
    def _kb_advance_pipeline(
        pipeline_id: str,
        notes: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        pipe_mgr = _get_pipeline_manager(ctx)
        result = pipe_mgr.advance(pipeline_id, notes=notes)
        return json.dumps(result, indent=2)

    # ── kb_skip_stage ──────────────────────────────────────────────

    @mcp.tool(
        name="kb_skip_stage",
        description=(
            "Skip to a specific pipeline stage "
            "(e.g., skip arch and go straight to review)."
        ),
    )
    def _kb_skip_stage(
        pipeline_id: str,
        stage: str,
        ctx: Optional[Context] = None,
    ) -> str:
        pipe_mgr = _get_pipeline_manager(ctx)
        result = pipe_mgr.skip_to(pipeline_id, stage)
        return json.dumps(result, indent=2)

    # ── kb_update_stage ────────────────────────────────────────────

    @mcp.tool(
        name="kb_update_stage",
        description=(
            "Update current stage stats: link session IDs, "
            "record approved/dismissed finding counts."
        ),
    )
    def _kb_update_stage(
        pipeline_id: str,
        session_id: str = "",
        approved: int = 0,
        dismissed: int = 0,
        ctx: Optional[Context] = None,
    ) -> str:
        pipe_mgr = _get_pipeline_manager(ctx)
        result = pipe_mgr.update_stage_stats(
            pipeline_id, session_id=session_id,
            approved=approved, dismissed=dismissed,
        )
        return json.dumps(result, indent=2)

    # ── kb_list_pipelines ──────────────────────────────────────────

    @mcp.tool(
        name="kb_list_pipelines",
        description="List all pipelines.",
    )
    def _kb_list_pipelines(ctx: Optional[Context] = None) -> str:
        pipe_mgr = _get_pipeline_manager(ctx)
        pipelines = pipe_mgr.list_all()
        return json.dumps([p.to_dict() for p in pipelines], indent=2)

    # ── kb_guide ─────────────────────────────────────────────────────

    @mcp.tool(
        name="kb_guide",
        description=(
            "Show the Swarm Suite workflow guide. Detects project type "
            "and shows the recommended pipeline with specific commands. "
            "Call at the start of any project analysis."
        ),
    )
    def _kb_guide(project_path: str = ".", ctx: Optional[Context] = None) -> str:
        config = _get_config(ctx)
        pipe_mgr = _get_pipeline_manager(ctx)
        pp = Path(project_path).resolve()

        # ── Detect project type ──────────────────────────────────────
        markers: dict[str, tuple[list[str], str]] = {
            "python": (
                ["pyproject.toml", "setup.py", "requirements.txt"],
                "python -m pytest --tb=short -q",
            ),
            "node": (
                ["package.json"],
                "npm test",
            ),
            "go": (
                ["go.mod"],
                "go test ./...",
            ),
            "rust": (
                ["Cargo.toml"],
                "cargo test",
            ),
            "dotnet": (
                [],  # handled by glob below
                "dotnet test",
            ),
            "embedded/c": (
                ["CMakeLists.txt", "Makefile", "platformio.ini"],
                "make test",
            ),
        }

        detected_types: list[str] = []
        test_commands: list[str] = []

        for lang, (files, cmd) in markers.items():
            if lang == "dotnet":
                if any(pp.glob("*.csproj")) or any(pp.glob("**/*.csproj")):
                    detected_types.append(lang)
                    test_commands.append(cmd)
                continue
            for fname in files:
                if (pp / fname).exists():
                    detected_types.append(lang)
                    test_commands.append(cmd)
                    break

        if detected_types:
            project_type = ", ".join(detected_types)
            test_command = "; ".join(test_commands)
        else:
            project_type = "unknown"
            test_command = "echo 'No test runner detected -- configure manually'"

        # ── Check for active pipeline ────────────────────────────────
        pp_str = str(pp)
        all_pipelines = pipe_mgr.list_all()
        active_pipeline = None
        for p in all_pipelines:
            p_resolved = str(Path(p.project_path).resolve())
            if p_resolved == pp_str:
                current = p.get_current()
                if current.status == "active":
                    active_pipeline = p
                    break

        pipeline_status_obj = None
        if active_pipeline:
            info = STAGE_INFO[active_pipeline.current_stage]
            pipeline_status_obj = {
                "id": active_pipeline.id,
                "stage": active_pipeline.current_stage,
                "stage_name": info["name"],
                "status": "active",
            }

        # ── Count existing sessions ──────────────────────────────────
        session_counts: dict[str, int] = {}
        for tool_name in TOOL_NAMES:
            sessions_dir = config.tool_sessions_path(tool_name)
            if sessions_dir.exists():
                session_counts[tool_name] = sum(
                    1 for e in sessions_dir.iterdir() if e.is_dir()
                )
            else:
                session_counts[tool_name] = 0

        total_sessions = sum(session_counts.values())

        # ── Build pipeline status string for the guide ───────────────
        if active_pipeline:
            info = STAGE_INFO[active_pipeline.current_stage]
            pipeline_display = (
                f"**ACTIVE** -- Pipeline `{active_pipeline.id}` "
                f"at Stage: {info['name']} (`{active_pipeline.current_stage}`)"
            )
        else:
            pipeline_display = "None"

        # ── Build guide ──────────────────────────────────────────────
        # Preamble for active pipeline
        active_preamble = ""
        if active_pipeline:
            info = STAGE_INFO[active_pipeline.current_stage]
            actions_md = "\n".join(f"  - {a}" for a in info["actions"])
            active_preamble = f"""
> **You have an active pipeline at Stage: {info['name']}** (`{active_pipeline.current_stage}`)
> Pipeline ID: `{active_pipeline.id}`
>
> **What to do next:**
{actions_md}

---

"""

        # Session notice
        session_notice = ""
        if total_sessions > 0 and not active_pipeline:
            session_notice = (
                f"\n> Found **{total_sessions}** existing session(s) "
                f"(arch: {session_counts.get('arch', 0)}, "
                f"review: {session_counts.get('review', 0)}, "
                f"fix: {session_counts.get('fix', 0)}, "
                f"doc: {session_counts.get('doc', 0)}). "
                f"Consider starting a pipeline to organize the workflow.\n\n---\n\n"
            )

        guide = f"""{active_preamble}{session_notice}# Swarm Suite \u2014 Pipeline Guide

## Your Project
- **Path:** {project_path}
- **Type:** {project_type}
- **Test command:** `{test_command}`
- **Active pipeline:** {pipeline_display}

## Workflow

### Stage 0: Hardware Spec Analysis (embedded projects)
*Skip this stage for pure software projects.*

```
kb_start_pipeline("{project_path}", include_spec=True)
spec_start_session("{project_path}")
spec_ingest(session_id, "path/to/datasheet.pdf")
```
- Parses datasheets, reference manuals, application notes
- Extracts: register maps, pin configs, protocols (CAN, SPI, I2C, EtherCAT, Modbus, etc.)
- Extracts: timing constraints, power specs, memory layout
- `spec_check_conflicts()` finds pin/bus/power conflicts
- `spec_export_for_arch()` posts hardware constraints to swarm-kb

**When done:** Review specs. `kb_advance_pipeline("<pipeline_id>")`

---

### Stage 1: Architecture Analysis
Analyze the project structure before looking at code details.

```
arch_analyze("{project_path}")
```
- Reviews: coupling, complexity, circular dependencies, module structure
- Findings are saved to swarm-kb automatically

For design questions, start a real multi-agent debate:
```
orchestrate_debate("{project_path}", topic="<your question>")
```
- 5-10 expert agents will analyze code and debate
- Result: architectural decision (ADR) saved to swarm-kb

**When done:** Review findings. Approve valid ones, dismiss false positives.
```
kb_advance_pipeline("<pipeline_id>")
```

---

### Stage 2: Code Review
Multi-expert review informed by architectural decisions from Stage 1.

```
orchestrate_review("{project_path}")
```
- 13 experts: security, performance, threading, error-handling, etc.
- Experts automatically receive ADRs as context
- Phase 1: experts review files independently
- Phase 2: experts cross-check each other's findings

**When done:** Review findings. `kb_advance_pipeline("<pipeline_id>")`

---

### Stage 3: Fix
Apply fixes for confirmed issues from both arch and review stages.

```
snapshot_tests("<session_id>")        \u2190 save test baseline FIRST
start_session(review_session="...", arch_session="...")
```
- 8 fix experts: refactoring, security-fix, performance-fix, etc.
- Experts propose fixes \u2192 cross-review \u2192 consensus \u2192 apply
- Only approved fixes are applied
- **Quality Gate:** After each fix iteration, run `kb_check_quality_gate(findings, fixes_applied, regressions, history)`
  - `recommendation="continue"` \u2192 fix more, re-review, re-check gate
  - `recommendation="stop_clean"` \u2192 advance to verify stage
  - `recommendation="stop_circuit_breaker"` \u2192 STOP, review manually (fix cycle is unstable)

**When done:** `kb_advance_pipeline("<pipeline_id>")`

---

### Stage 4: Regression Check
Verify fixes didn't break anything.

```
check_regression("<session_id>")
kb_check_quality_gate(findings, fixes_applied, regressions, history)
```
- Syntax validation on modified files
- Test suite comparison (before vs after)
- Re-scan for new issues
- Quality gate confirms stability before advancing

If regression detected \u2192 investigate, fix, re-check.

**When done:** `kb_advance_pipeline("<pipeline_id>")` \u2192 Pipeline complete!

---

### Stage 5: Documentation
Update docs to reflect changes.

```
doc_verify("{project_path}")          \u2190 find stale docs
doc_generate("{project_path}")        \u2190 update API docs
```

**When done:** `kb_advance_pipeline("<pipeline_id>")` \u2192 Pipeline complete!

---

## Quick Start

**For embedded/hardware projects:**
```
kb_start_pipeline("{project_path}", include_spec=True)
```
Starts at Stage 0 (spec analysis) \u2192 ingest datasheets \u2192 architecture \u2192 review \u2192 fix \u2192 verify \u2192 docs.

**For software projects:**
```
kb_start_pipeline("{project_path}")
```
Starts at Stage 1 (architecture) \u2192 review \u2192 fix \u2192 verify \u2192 docs.

Or run individual tools without a pipeline \u2014 they work independently too.

## Key Principle
Each stage has a **user gate** \u2014 you review results and decide when to advance.
No automatic progression. You control the pace.
"""

        return json.dumps({
            "project_path": project_path,
            "project_type": project_type,
            "test_command": test_command,
            "active_pipeline": pipeline_status_obj,
            "existing_sessions": session_counts,
            "guide": guide,
        }, indent=2)

    # ── kb_check_quality_gate ─────────────────────────────────────────

    @mcp.tool(
        name="kb_check_quality_gate",
        description=(
            "Check if the review-fix cycle meets quality thresholds. "
            "Pass findings from the current review round. Returns: passed, "
            "circuit breaker status, and recommendation (continue/stop)."
        ),
    )
    def _kb_check_quality_gate(
        findings: str,           # JSON array of finding dicts
        fixes_applied: int = 0,
        regressions: int = 0,
        history: str = "",       # JSON array of previous RoundMetrics dicts
        thresholds: str = "",    # JSON object of custom thresholds (optional)
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            findings_list = json.loads(findings)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid findings JSON: {exc}"})

        metrics = compute_round_metrics(
            findings_list,
            fixes_applied=fixes_applied,
            regressions=regressions,
        )

        # Parse history
        history_list: list[RoundMetrics] = []
        if history:
            try:
                raw_history = json.loads(history)
                for h in raw_history:
                    rm = RoundMetrics()
                    for k, v in h.items():
                        if hasattr(rm, k):
                            setattr(rm, k, v)
                    history_list.append(rm)
            except json.JSONDecodeError as exc:
                return json.dumps({"error": f"Invalid history JSON: {exc}"})

        # Parse thresholds or load from config
        gate_thresholds: GateThresholds
        if thresholds:
            try:
                raw_thresholds = json.loads(thresholds)
                gate_thresholds = GateThresholds.from_dict(raw_thresholds)
            except json.JSONDecodeError as exc:
                return json.dumps({"error": f"Invalid thresholds JSON: {exc}"})
        else:
            config = _get_config(ctx)
            gate_path = config.kb_root / "quality_gate.json"
            gate_thresholds = load_thresholds(gate_path)

        result = check_gate(metrics, history=history_list, thresholds=gate_thresholds)
        return json.dumps(result.to_dict(), indent=2)

    # ── kb_configure_quality_gate ─────────────────────────────────────

    @mcp.tool(
        name="kb_configure_quality_gate",
        description=(
            "Configure quality gate thresholds for a project. "
            "Saves to ~/.swarm-kb/quality_gate.json"
        ),
    )
    def _kb_configure_quality_gate(
        max_critical: int = 0,
        max_high: int = 0,
        max_medium: int = 3,
        max_weighted_score: int = 8,
        consecutive_clean_rounds: int = 2,
        max_iterations: int = 7,
        max_regression_rate: float = 0.10,
        max_stale_rounds: int = 3,
        score_increase_limit: int = 2,
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        gate_thresholds = GateThresholds(
            max_critical=max_critical,
            max_high=max_high,
            max_medium=max_medium,
            max_weighted_score=max_weighted_score,
            consecutive_clean_rounds=consecutive_clean_rounds,
            max_regression_rate=max_regression_rate,
            max_iterations=max_iterations,
            max_stale_rounds=max_stale_rounds,
            score_increase_limit=score_increase_limit,
        )
        gate_path = config.kb_root / "quality_gate.json"
        save_thresholds(gate_thresholds, gate_path)
        return json.dumps({
            "status": "saved",
            "path": str(gate_path),
            "thresholds": gate_thresholds.to_dict(),
        }, indent=2)

    # ── kb_get_quality_gate ──────────────────────────────────────────

    @mcp.tool(
        name="kb_get_quality_gate",
        description="Get current quality gate thresholds.",
    )
    def _kb_get_quality_gate(ctx: Optional[Context] = None) -> str:
        config = _get_config(ctx)
        gate_path = config.kb_root / "quality_gate.json"
        gate_thresholds = load_thresholds(gate_path)
        return json.dumps({
            "path": str(gate_path),
            "thresholds": gate_thresholds.to_dict(),
        }, indent=2)

    # ── kb_read_document ──────────────────────────────────────────────

    @mcp.tool(
        name="kb_read_document",
        description=(
            "Parse a PDF, text, or CSV document into AI-readable structured format. "
            "Extracts text, tables, headings, and metadata."
        ),
    )
    def _kb_read_document(
        document_path: str,
        max_pages: int = 0,
        output: str = "ai_readable",  # "ai_readable" | "structured" | "text_only"
        ctx: Optional[Context] = None,
    ) -> str:
        from .doc_reader import parse_document
        doc = parse_document(document_path, max_pages=max_pages)
        if output == "ai_readable":
            return doc.to_ai_readable()
        elif output == "text_only":
            return doc.full_text
        else:
            return json.dumps(doc.to_dict(), indent=2)

    # ── kb_read_document_pages ────────────────────────────────────────

    @mcp.tool(
        name="kb_read_document_pages",
        description=(
            "Read specific pages from a PDF document. "
            "Use for large documents where you only need a section."
        ),
    )
    def _kb_read_document_pages(
        document_path: str,
        start_page: int = 1,
        end_page: int = 10,
        ctx: Optional[Context] = None,
    ) -> str:
        from .doc_reader import parse_document
        doc = parse_document(document_path, max_pages=end_page)
        # Filter to requested page range
        filtered_pages = [p for p in doc.pages if start_page <= p.page_number <= end_page]

        parts = []
        parts.append(f"# {doc.title or Path(document_path).name}")
        parts.append(f"- Format: {doc.format}")
        parts.append(f"- Total pages: {doc.total_pages}")
        parts.append(f"- Showing pages: {start_page}-{min(end_page, doc.total_pages)}")
        if doc.metadata:
            for k, v in doc.metadata.items():
                if v:
                    parts.append(f"- {k}: {v}")
        parts.append("")

        for page in filtered_pages:
            parts.append(f"\n--- Page {page.page_number} ---\n")
            if page.headings:
                for h in page.headings:
                    parts.append(f"## {h}")
            from .doc_reader import _clean_text, _table_to_markdown
            clean = _clean_text(page.text)
            if clean.strip():
                parts.append(clean)
            for i, table in enumerate(page.tables):
                parts.append(f"\n**Table {i+1} (page {page.page_number}):**\n")
                parts.append(_table_to_markdown(table))

        return "\n".join(parts)

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
