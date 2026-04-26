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

# New tool surfaces -- see docs/decisions/2026-04-26-stage-*.md
from . import idea_session as _idea
from . import plan_session as _plan
from . import hardening_session as _harden
from . import release_session as _release
from . import lite_tools as _lite

_log = logging.getLogger("swarm_kb.server")


def create_mcp_server():
    """Create and configure the swarm-kb MCP server."""
    from dataclasses import dataclass as _dataclass
    from mcp.server.fastmcp import FastMCP, Context
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    from .judging import JudgingEngine
    from .verification import VerificationStore
    from .pgve import PgveStore
    from .dsl import FlowStore

    @_dataclass
    class _LifespanState:
        config: SuiteConfig
        debate_engine: DebateEngine
        pipeline_manager: PipelineManager
        decision_store: DecisionStore
        debate_store: DebateStore
        judging_engine: JudgingEngine
        verification_store: VerificationStore
        pgve_store: PgveStore
        flow_store: FlowStore

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[_LifespanState]:
        config = bootstrap()
        engine = DebateEngine(config.debates_path / "active")
        pipe_mgr = PipelineManager(config.pipelines_path)
        dec_store = DecisionStore(config.decisions_path / "decisions.jsonl")
        dbt_store = DebateStore(config.debates_path / "debates.jsonl")
        judge_eng = JudgingEngine(config.kb_root / "judgings" / "active")
        verify_store = VerificationStore(config.kb_root / "verifications" / "active")
        pgve_store = PgveStore(config.kb_root / "pgve" / "active")
        flow_store = FlowStore(config.kb_root / "flows" / "active")
        yield _LifespanState(
            config=config,
            debate_engine=engine,
            pipeline_manager=pipe_mgr,
            decision_store=dec_store,
            debate_store=dbt_store,
            judging_engine=judge_eng,
            verification_store=verify_store,
            pgve_store=pgve_store,
            flow_store=flow_store,
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

    def _get_judging_engine(ctx: Optional[Context]):
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context.judging_engine

    def _get_verification_store(ctx: Optional[Context]):
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context.verification_store

    def _get_pgve_store(ctx: Optional[Context]):
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context.pgve_store

    def _get_flow_store(ctx: Optional[Context]):
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context.flow_store

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
        except ValueError:
            raise
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
        except ValueError:
            raise
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
        except ValueError:
            raise
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
        except ValueError:
            raise
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
                raise ValueError(f"Debate {debate_id!r} not found")
            return json.dumps(debate.to_dict())
        except ValueError:
            raise
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
        except ValueError:
            raise
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
        except ValueError:
            raise
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
            "Call after reviewing current stage results. "
            "Stage gates: idea/plan/harden require their session content "
            "to be finalized; pass force=True to override."
        ),
    )
    def _kb_advance_pipeline(
        pipeline_id: str,
        notes: str = "",
        force: bool = False,
        ctx: Optional[Context] = None,
    ) -> str:
        from .stage_gates import check_stage_gate
        pipe_mgr = _get_pipeline_manager(ctx)
        config = _get_config(ctx)
        pipe = pipe_mgr.get(pipeline_id)
        if pipe is None:
            return json.dumps({"error": f"Pipeline {pipeline_id} not found"})
        if not force:
            ok, msg = check_stage_gate(pipe.current_stage, config)
            if not ok:
                return json.dumps({
                    "error": "stage gate not satisfied",
                    "stage": pipe.current_stage,
                    "hint": msg,
                    "override": "Re-run with force=True to advance anyway.",
                })
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
            findings_parsed = json.loads(findings)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid findings JSON: {exc}"})

        # Accept both formats:
        #   - list of finding dicts: [{"severity": "high", ...}, ...]
        #   - severity counts dict:  {"critical": 0, "high": 2, "medium": 4, "low": 12}
        if isinstance(findings_parsed, dict) and not findings_parsed.get("severity"):
            severity_keys = {"critical", "high", "medium", "low", "info"}
            if severity_keys & set(findings_parsed.keys()):
                findings_list = []
                for sev in ("critical", "high", "medium", "low", "info"):
                    count = int(findings_parsed.get(sev, 0))
                    findings_list.extend(
                        {"severity": sev, "title": f"{sev}-{i+1}"}
                        for i in range(count)
                    )
            else:
                findings_list = [findings_parsed]
        elif isinstance(findings_parsed, list):
            findings_list = findings_parsed
        else:
            return json.dumps({"error": "findings must be a JSON array of finding dicts or a severity counts dict"})

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

    # ════════════════════════════════════════════════════════════════════
    # Stage 0a Idea -- drives the brainstorming skill
    # ════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="kb_start_idea_session",
        description="Open a new Idea session. Drives the `brainstorming` skill: ask one question per turn, record answers, present 2-3 alternatives, finalize design.",
    )
    def _kb_start_idea(project_path: str, prompt: str, name: str = "",
                       ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _idea.start_idea_session(
            cfg.tool_sessions_path("idea"),
            project_path=project_path, prompt=prompt, name=name,
        )
        return json.dumps(out, indent=2)

    @mcp.tool(
        name="kb_capture_idea_answer",
        description="Phase 1 of brainstorming: record one Q&A pair into the Idea session.",
    )
    def _kb_capture_idea(session_id: str, question: str, answer: str,
                         ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _idea.capture_idea_answer(
            cfg.tool_sessions_path("idea"),
            session_id=session_id, question=question, answer=answer,
        )
        return json.dumps(out)

    @mcp.tool(
        name="kb_record_idea_alternatives",
        description="Phase 2 of brainstorming: record 2-3 design alternatives + the user's chosen one.",
    )
    def _kb_record_alternatives(session_id: str, alternatives: list[dict],
                                chosen_id: str = "",
                                ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _idea.record_alternatives(
            cfg.tool_sessions_path("idea"),
            session_id=session_id, alternatives=alternatives, chosen_id=chosen_id,
        )
        return json.dumps(out)

    @mcp.tool(
        name="kb_finalize_idea_design",
        description="Phase 3+5 of brainstorming: persist the consolidated design and mark the session ready to advance to Architecture.",
    )
    def _kb_finalize_design(session_id: str, design_md: str,
                            ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _idea.finalize_idea_design(
            cfg.tool_sessions_path("idea"),
            session_id=session_id, design_md=design_md,
        )
        return json.dumps(out)

    # ════════════════════════════════════════════════════════════════════
    # Stage 2 Plan -- drives the writing_plans skill
    # ════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="kb_start_plan_session",
        description="Open a Plan session anchored to one or more ADRs. Drives the `writing_plans` skill: bite-sized 2-5-minute tasks, each with failing test first.",
    )
    def _kb_start_plan(project_path: str, adr_ids: list[str], name: str = "",
                       ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _plan.start_plan_session(
            cfg.tool_sessions_path("plan"),
            project_path=project_path, adr_ids=adr_ids, name=name,
        )
        return json.dumps(out)

    @mcp.tool(
        name="kb_emit_task",
        description="Append one task (Markdown body) to the Plan session's tasks.jsonl.",
    )
    def _kb_emit_task(session_id: str, task_md: str,
                      ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _plan.emit_task(
            cfg.tool_sessions_path("plan"),
            session_id=session_id, task_md=task_md,
        )
        return json.dumps(out)

    @mcp.tool(
        name="kb_finalize_plan",
        description="Persist plan.md and validate it against the writing_plans contract. Returns {validated, errors}. On success, the pipeline can advance to Review.",
    )
    def _kb_finalize_plan(session_id: str, plan_md: str,
                          ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _plan.finalize_plan(
            cfg.tool_sessions_path("plan"),
            session_id=session_id, plan_md=plan_md,
        )
        return json.dumps(out)

    # ════════════════════════════════════════════════════════════════════
    # Stage 6 Hardening -- production-readiness checks
    # ════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="kb_start_hardening",
        description="Open a Hardening session for a project. Lists the available checks (typecheck, coverage, dep_audit, secrets, dep_hygiene, ci_presence, observability).",
    )
    def _kb_start_harden(project_path: str, min_coverage: int = 85,
                         name: str = "",
                         ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _harden.start_hardening(
            cfg.tool_sessions_path("harden"),
            project_path=project_path, min_coverage=min_coverage, name=name,
        )
        return json.dumps(out)

    @mcp.tool(
        name="kb_run_check",
        description="Run one hardening check by name. Tools that aren't installed degrade to {installed: false} -- the user sees what's missing instead of a crash.",
    )
    def _kb_run_check(session_id: str, check: str,
                      ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _harden.run_check(
            cfg.tool_sessions_path("harden"),
            session_id=session_id, check=check,
        )
        return json.dumps(out)

    @mcp.tool(
        name="kb_get_hardening_report",
        description="Aggregate all run checks into a Markdown report. Reports {blockers, skipped, total_checks}.",
    )
    def _kb_harden_report(session_id: str,
                          ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _harden.get_hardening_report(
            cfg.tool_sessions_path("harden"),
            session_id=session_id,
        )
        return json.dumps(out)

    # ════════════════════════════════════════════════════════════════════
    # Stage 7 Release -- never auto-publishes; user runs twine
    # ════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="kb_start_release",
        description="Open a Release session for a project.",
    )
    def _kb_start_release(project_path: str, name: str = "",
                          ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _release.start_release(
            cfg.tool_sessions_path("release"),
            project_path=project_path, name=name,
        )
        return json.dumps(out)

    @mcp.tool(
        name="kb_propose_version_bump",
        description="Read git log since last tag; propose patch / minor / major bump using Conventional Commits prefixes.",
    )
    def _kb_propose_bump(session_id: str,
                         ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _release.propose_version_bump(
            cfg.tool_sessions_path("release"), session_id=session_id,
        )
        return json.dumps(out)

    @mcp.tool(
        name="kb_generate_changelog",
        description="Draft a CHANGELOG.md entry from commits since the last tag, grouped by Conventional Commits prefix.",
    )
    def _kb_gen_changelog(session_id: str,
                          ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _release.generate_changelog(
            cfg.tool_sessions_path("release"), session_id=session_id,
        )
        return json.dumps(out)

    @mcp.tool(
        name="kb_validate_pyproject",
        description="Check pyproject.toml for PyPI-required fields (name, version, description, license, authors, readme, requires-python) plus LICENSE file presence.",
    )
    def _kb_validate_pp(session_id: str, path: str = "pyproject.toml",
                        ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _release.validate_pyproject(
            cfg.tool_sessions_path("release"), session_id=session_id, path=path,
        )
        return json.dumps(out)

    @mcp.tool(
        name="kb_build_dist",
        description="Run `python -m build` and report the resulting artifacts in dist/.",
    )
    def _kb_build(session_id: str,
                  ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _release.build_dist(
            cfg.tool_sessions_path("release"), session_id=session_id,
        )
        return json.dumps(out)

    @mcp.tool(
        name="kb_release_summary",
        description="Aggregate version bump + pyproject validation + build status into a 'ready to twine upload' checklist. NEVER auto-publishes.",
    )
    def _kb_release_summary(session_id: str,
                            ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _release.release_summary(
            cfg.tool_sessions_path("release"), session_id=session_id,
        )
        return json.dumps(out)

    # ════════════════════════════════════════════════════════════════════
    # Lite-mode -- escape hatch from full pipeline ceremony
    # ════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="kb_quick_review",
        description="One-shot review: post a single finding without opening a review session. Persists to ~/.swarm-kb/lite/<YYYY-MM-DD>/.",
    )
    def _kb_quick_review(file: str, line_start: int, line_end: int,
                         severity: str, title: str, expert_role: str,
                         actual: str = "", expected: str = "",
                         source_ref: str = "", confidence: float = 0.7,
                         ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _lite.kb_quick_review(
            file=file, line_start=line_start, line_end=line_end,
            severity=severity, title=title, expert_role=expert_role,
            actual=actual, expected=expected, source_ref=source_ref,
            confidence=confidence, config=cfg,
        )
        return json.dumps(out)

    @mcp.tool(
        name="kb_quick_fix",
        description="One-shot fix proposal: record intent without opening a fix session. The patch is NOT applied -- the caller edits the file. Persists to ~/.swarm-kb/lite/<YYYY-MM-DD>/.",
    )
    def _kb_quick_fix(file: str, line_start: int, line_end: int,
                      old_text: str, new_text: str, rationale: str,
                      expert_role: str, finding_id: str = "",
                      ctx: Optional[Context] = None) -> str:
        cfg = _get_config(ctx)
        out = _lite.kb_quick_fix(
            file=file, line_start=line_start, line_end=line_end,
            old_text=old_text, new_text=new_text, rationale=rationale,
            expert_role=expert_role, finding_id=finding_id, config=cfg,
        )
        return json.dumps(out)

    # ════════════════════════════════════════════════════════════════════
    # Pipeline backward navigation
    # ════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="kb_rewind_pipeline",
        description="Rewind a pipeline to an earlier stage. Used when discoveries in stage N invalidate decisions from stage M < N (e.g. Review finds the ADR was wrong). Reason is recorded in the target stage's notes.",
    )
    def _kb_rewind(pipeline_id: str, stage: str, reason: str = "",
                   ctx: Optional[Context] = None) -> str:
        pipe_mgr = _get_pipeline_manager(ctx)
        return json.dumps(pipe_mgr.rewind(pipeline_id, stage, reason=reason), indent=2)

    # ════════════════════════════════════════════════════════════════════
    # CLAUDE.md keeper
    # ════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="kb_check_claude_md",
        description="Audit a CLAUDE.md file for size, accreted bug-fix recipes, missing required sections, and missing pointers. Used as a kb_advance_pipeline gate.",
    )
    def _kb_keep_claude(path: str = "CLAUDE.md",
                        ctx: Optional[Context] = None) -> str:
        from swarm_core.keeper.server import kb_check_claude_md
        return json.dumps(kb_check_claude_md(path), indent=2)

    # ════════════════════════════════════════════════════════════════════
    # Self-direction / completion tools
    # ════════════════════════════════════════════════════════════════════

    from .completion_store import CompletionStore as _CompletionStore

    def _resolve_session_dir(cfg: SuiteConfig, tool: str, session_id: str) -> Path:
        if tool not in TOOL_NAMES:
            raise ValueError(
                f"unknown tool {tool!r}; expected one of {list(TOOL_NAMES)}"
            )
        if not session_id:
            raise ValueError("session_id must be non-empty")
        sess_dir = cfg.tool_sessions_path(tool) / session_id
        if not sess_dir.is_dir():
            raise ValueError(
                f"session {tool}/{session_id} not found at {sess_dir}; "
                "create the session first."
            )
        return sess_dir

    @mcp.tool(
        name="kb_subtask_done",
        description=(
            "Agent self-signal: subtask `subtask_id` is finished. "
            "Idempotent on subtask_id; re-marking the same id bumps a "
            "loop counter and eventually trips the cap. Resets the "
            "consecutive-thinks counter. Use this every time the agent "
            "completes a discrete unit of work so the host can stop the "
            "loop without parsing free-text."
        ),
    )
    def _kb_subtask_done(
        tool: str,
        session_id: str,
        subtask_id: str,
        summary: str = "",
        outputs: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        cfg = _get_config(ctx)
        sess_dir = _resolve_session_dir(cfg, tool, session_id)
        outputs_dict = json.loads(outputs) if outputs else {}
        store = _CompletionStore(sess_dir, session_id)
        record = store.mark_subtask_done(
            subtask_id, summary=summary, outputs=outputs_dict,
        )
        return json.dumps({
            "subtask": record.to_dict(),
            "state": store.state().to_dict(),
        }, indent=2)

    @mcp.tool(
        name="kb_complete_task",
        description=(
            "Agent self-signal: the whole task for this session is done. "
            "Idempotent -- re-calling returns the existing completion "
            "record without overwriting summary or outputs. After this "
            "call, kb_subtask_done and kb_record_think raise."
        ),
    )
    def _kb_complete_task(
        tool: str,
        session_id: str,
        summary: str,
        outputs: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        cfg = _get_config(ctx)
        sess_dir = _resolve_session_dir(cfg, tool, session_id)
        outputs_dict = json.loads(outputs) if outputs else {}
        store = _CompletionStore(sess_dir, session_id)
        record = store.complete_task(summary, outputs=outputs_dict)
        return json.dumps({
            "completion": record.to_dict(),
            "state": store.state().to_dict(),
        }, indent=2)

    @mcp.tool(
        name="kb_record_think",
        description=(
            "Agent self-signal: a thought step occurred without an "
            "action. Bumps the consecutive-thinks counter; trips the "
            "cap when the agent is spinning without progress."
        ),
    )
    def _kb_record_think(
        tool: str,
        session_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        cfg = _get_config(ctx)
        sess_dir = _resolve_session_dir(cfg, tool, session_id)
        store = _CompletionStore(sess_dir, session_id)
        counter = store.record_think()
        return json.dumps({
            "consecutive_thinks": counter,
            "caps": store.caps,
        }, indent=2)

    @mcp.tool(
        name="kb_get_completion",
        description=(
            "Read the completion state for a session: subtasks done, "
            "loop counts, completion record (or null), think counter, "
            "caps. Safe to call any time."
        ),
    )
    def _kb_get_completion(
        tool: str,
        session_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        cfg = _get_config(ctx)
        sess_dir = _resolve_session_dir(cfg, tool, session_id)
        store = _CompletionStore(sess_dir, session_id)
        should_stop, reason = store.should_stop()
        return json.dumps({
            "state": store.state().to_dict(),
            "caps": store.caps,
            "should_stop": should_stop,
            "stop_reason": reason,
        }, indent=2)

    @mcp.tool(
        name="kb_record_action",
        description=(
            "Agent self-signal: a side-effectful action (file write, "
            "shell command) happened that isn't itself a tracked "
            "subtask. Resets the consecutive-thinks counter so the "
            "agent doesn't trip max_consecutive_thinks while making "
            "real progress. Idempotent."
        ),
    )
    def _kb_record_action(
        tool: str,
        session_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        cfg = _get_config(ctx)
        sess_dir = _resolve_session_dir(cfg, tool, session_id)
        store = _CompletionStore(sess_dir, session_id)
        store.record_action()
        return json.dumps({
            "consecutive_thinks": store.state().consecutive_thinks,
            "caps": store.caps,
        }, indent=2)

    # ════════════════════════════════════════════════════════════════════
    # Debate format registry (4 protocols over the same DebateEngine)
    # ════════════════════════════════════════════════════════════════════

    from . import debate_formats as _fmts

    @mcp.tool(
        name="kb_list_debate_formats",
        description=(
            "List all registered debate formats with one-line summaries. "
            "Pick one to pass as `format=` to start_debate."
        ),
    )
    def _kb_list_debate_formats(ctx: Optional[Context] = None) -> str:
        return json.dumps(
            [
                {"name": _fmts.get_format(n).name,
                 "summary": _fmts.get_format(n).summary,
                 "actors": _fmts.get_format(n).actors}
                for n in _fmts.list_formats()
            ],
            indent=2,
        )

    @mcp.tool(
        name="kb_get_debate_format",
        description=(
            "Get the full phase spec for a debate format (open, "
            "with_judge, trial, mediation): actors, phases, expected "
            "tool calls per phase, stop condition, notes. Agents read "
            "this to know what to do next in their format."
        ),
    )
    def _kb_get_debate_format(
        format: str,
        ctx: Optional[Context] = None,
    ) -> str:
        return json.dumps(_fmts.get_format(format).to_dict(), indent=2)

    # ════════════════════════════════════════════════════════════════════
    # CouncilAsAJudge -- multi-dimensional judging with rationales
    # ════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="kb_start_judging",
        description=(
            "Open a CouncilAsAJudge session over a subject. N judges "
            "will each judge ONE dimension and submit a verdict + "
            "rationale. Default dimensions: accuracy, helpfulness, "
            "harmlessness, coherence, conciseness, instruction_adherence."
        ),
    )
    def _kb_start_judging(
        subject: str,
        dimensions: str = "",
        subject_kind: str = "text",
        subject_ref: str = "",
        project_path: str = "",
        source_tool: str = "",
        source_session: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        engine = _get_judging_engine(ctx)
        dims = [d.strip() for d in dimensions.split(",") if d.strip()] or None
        j = engine.start(
            subject=subject,
            dimensions=dims,
            subject_kind=subject_kind,
            subject_ref=subject_ref,
            project_path=project_path,
            source_tool=source_tool,
            source_session=source_session,
        )
        return json.dumps(j.to_dict(), indent=2)

    @mcp.tool(
        name="kb_judge_dimension",
        description=(
            "One judge submits a verdict + rationale for ONE dimension "
            "of an open judging. Verdict in {pass, fail, mixed, "
            "abstain}. Re-judging the same dimension by the same judge "
            "overwrites the prior submission."
        ),
    )
    def _kb_judge_dimension(
        judging_id: str,
        judge: str,
        dimension: str,
        verdict: str,
        rationale: str,
        suggested_changes: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        engine = _get_judging_engine(ctx)
        changes = [c.strip() for c in suggested_changes.split("\n") if c.strip()]
        jid = engine.judge(
            judging_id,
            judge=judge,
            dimension=dimension,
            verdict=verdict,
            rationale=rationale,
            suggested_changes=changes,
        )
        j = engine.get(judging_id)
        return json.dumps({
            "judgment_id": jid,
            "covered_dimensions": sorted(j.covered_dimensions()) if j else [],
            "is_complete": j.is_complete() if j else False,
        }, indent=2)

    @mcp.tool(
        name="kb_resolve_judging",
        description=(
            "Synthesise per-dimension judgments into a single verdict "
            "(pass/fail/mixed) with a summary rationale. The aggregator "
            "is the agent calling this tool -- the verdict and summary "
            "are its synthesis, not auto-derived."
        ),
    )
    def _kb_resolve_judging(
        judging_id: str,
        overall: str,
        summary: str,
        synthesised_by: str = "",
        follow_ups: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        engine = _get_judging_engine(ctx)
        ups = [u.strip() for u in follow_ups.split("\n") if u.strip()]
        synth = engine.synthesise(
            judging_id,
            overall=overall,
            summary=summary,
            synthesised_by=synthesised_by,
            follow_ups=ups,
        )
        return json.dumps(synth.to_dict(), indent=2)

    @mcp.tool(
        name="kb_get_judging",
        description=(
            "Read a judging by ID: subject, dimensions, all judgments "
            "so far, synthesis (or null), status."
        ),
    )
    def _kb_get_judging(
        judging_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        engine = _get_judging_engine(ctx)
        j = engine.get(judging_id)
        if j is None:
            raise ValueError(f"Judging {judging_id!r} not found")
        return json.dumps(j.to_dict(), indent=2)

    @mcp.tool(
        name="kb_list_judgings",
        description=(
            "List judgings across the suite. Filter by status "
            "(open/resolved/cancelled) and source_tool."
        ),
    )
    def _kb_list_judgings(
        status: str = "",
        source_tool: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        engine = _get_judging_engine(ctx)
        items = engine.list_all(status=status, source_tool=source_tool)
        return json.dumps([j.to_dict() for j in items], indent=2)

    # ════════════════════════════════════════════════════════════════════
    # Verification stage -- aggregated artifact between fix and doc
    # ════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="kb_start_verification",
        description=(
            "Open a VerificationReport for a fix-session. The orchestrator "
            "feeds evidence (test diff, regression scan, quality-gate "
            "result, optional judgings) via kb_add_verification_evidence, "
            "then synthesises a verdict via kb_finalise_verification. The "
            "verdict gates advancement into the doc stage."
        ),
    )
    def _kb_start_verification(
        fix_session: str,
        review_session: str = "",
        project_path: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_verification_store(ctx)
        report = store.start(
            fix_session=fix_session,
            review_session=review_session,
            project_path=project_path,
        )
        return json.dumps(report.to_dict(), indent=2)

    @mcp.tool(
        name="kb_add_verification_evidence",
        description=(
            "Attach one piece of evidence (test_diff, regression_scan, "
            "quality_gate, judging, manual_note) to an open verification. "
            "`data` is a JSON-encoded dict whose shape depends on `kind`."
        ),
    )
    def _kb_add_verification_evidence(
        report_id: str,
        kind: str,
        summary: str,
        data: str = "",
        source_tool: str = "",
        source_session: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_verification_store(ctx)
        data_dict = json.loads(data) if data else {}
        ev_id = store.add_evidence(
            report_id,
            kind=kind,
            summary=summary,
            data=data_dict,
            source_tool=source_tool,
            source_session=source_session,
        )
        return json.dumps({"evidence_id": ev_id}, indent=2)

    @mcp.tool(
        name="kb_finalise_verification",
        description=(
            "Synthesise the evidence into a verdict (pass/fail/partial). "
            "blocking_issues and follow_ups are newline-separated. After "
            "this call, the report is read-only."
        ),
    )
    def _kb_finalise_verification(
        report_id: str,
        overall: str,
        summary: str,
        blocking_issues: str = "",
        follow_ups: str = "",
        synthesised_by: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_verification_store(ctx)
        block = [b.strip() for b in blocking_issues.split("\n") if b.strip()]
        ups = [u.strip() for u in follow_ups.split("\n") if u.strip()]
        verdict = store.finalise(
            report_id,
            overall=overall,
            summary=summary,
            blocking_issues=block,
            follow_ups=ups,
            synthesised_by=synthesised_by,
        )
        return json.dumps(verdict.to_dict(), indent=2)

    @mcp.tool(
        name="kb_get_verification",
        description="Read a verification report by ID: evidence list + verdict + status.",
    )
    def _kb_get_verification(
        report_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_verification_store(ctx)
        r = store.get(report_id)
        if r is None:
            raise ValueError(f"Verification {report_id!r} not found")
        return json.dumps(r.to_dict(), indent=2)

    @mcp.tool(
        name="kb_list_verifications",
        description=(
            "List verifications. Filter by status (open/finalised/cancelled) "
            "or fix_session."
        ),
    )
    def _kb_list_verifications(
        status: str = "",
        fix_session: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_verification_store(ctx)
        items = store.list_all(status=status, fix_session=fix_session)
        return json.dumps([r.to_dict() for r in items], indent=2)

    # ════════════════════════════════════════════════════════════════════
    # Planner-Generator-Evaluator (generate-verify-retry loop)
    # ════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="kb_start_pgve",
        description=(
            "Open a generate-verify-retry session for one task. The "
            "generator submits a candidate via kb_submit_candidate; the "
            "evaluator scores it via kb_evaluate_candidate. While the "
            "verdict is 'revise', generator submits another candidate "
            "carrying the previous feedback. Stops on 'accepted' or "
            "when the candidate budget is exhausted."
        ),
    )
    def _kb_start_pgve(
        task_spec: str,
        max_candidates: int = 5,
        project_path: str = "",
        source_tool: str = "",
        source_session: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_pgve_store(ctx)
        s = store.start(
            task_spec=task_spec,
            max_candidates=max_candidates,
            project_path=project_path,
            source_tool=source_tool,
            source_session=source_session,
        )
        return json.dumps(s.to_dict(), indent=2)

    @mcp.tool(
        name="kb_submit_candidate",
        description=(
            "Generator submits a candidate for the latest open pgve "
            "session. The candidate auto-carries the previous "
            "evaluation's feedback in its `previous_feedback` field so "
            "downstream agents can read it without re-querying JSONL."
        ),
    )
    def _kb_submit_candidate(
        session_id: str,
        generator: str,
        content: str,
        payload: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_pgve_store(ctx)
        payload_dict = json.loads(payload) if payload else {}
        cand = store.submit_candidate(
            session_id,
            generator=generator,
            content=content,
            payload=payload_dict,
        )
        return json.dumps(cand.to_dict(), indent=2)

    @mcp.tool(
        name="kb_evaluate_candidate",
        description=(
            "Evaluator scores the LATEST candidate of a pgve session. "
            "Verdict in {accepted, revise, rejected}. accepted -> "
            "session finalises with this candidate as winner; revise -> "
            "generator is expected to retry with the feedback; "
            "rejected -> the planner should produce a fresh task spec."
        ),
    )
    def _kb_evaluate_candidate(
        session_id: str,
        evaluator: str,
        verdict: str,
        feedback: str,
        score: float = -1.0,
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_pgve_store(ctx)
        ev = store.evaluate(
            session_id,
            evaluator=evaluator,
            verdict=verdict,
            feedback=feedback,
            score=None if score < 0 else score,
        )
        # Return both the evaluation AND the session so the caller sees
        # whether to retry (status=open) or stop (accepted/exhausted/rejected).
        s = store.get(session_id)
        return json.dumps({
            "evaluation": ev.to_dict(),
            "session_status": s.status if s else "unknown",
            "remaining_budget": s.remaining_budget() if s else 0,
        }, indent=2)

    @mcp.tool(
        name="kb_get_pgve",
        description="Read a pgve session by ID: candidates + evaluations + status.",
    )
    def _kb_get_pgve(
        session_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_pgve_store(ctx)
        s = store.get(session_id)
        if s is None:
            raise ValueError(f"PgveSession {session_id!r} not found")
        return json.dumps(s.to_dict(), indent=2)

    @mcp.tool(
        name="kb_list_pgve",
        description=(
            "List pgve sessions. Filter by status "
            "(open/accepted/exhausted/rejected/cancelled) or source_tool."
        ),
    )
    def _kb_list_pgve(
        status: str = "",
        source_tool: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_pgve_store(ctx)
        items = store.list_all(status=status, source_tool=source_tool)
        return json.dumps([s.to_dict() for s in items], indent=2)

    # ════════════════════════════════════════════════════════════════════
    # Flow DSL -- declarative pipeline routing (a -> b, c -> d, H, e)
    # ════════════════════════════════════════════════════════════════════

    from . import dsl as _dsl

    @mcp.tool(
        name="kb_parse_flow",
        description=(
            "Parse a flow DSL string and return its AST + validation "
            "problems. Use to dry-run a routing expression before "
            "starting it. Grammar: `->` sequence, `,` parallel, `H` "
            "human gate, parens grouping. `known_names` (newline list) "
            "validates that every step name is registered."
        ),
    )
    def _kb_parse_flow(
        source: str,
        known_names: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        ast = _dsl.parse_flow(source)
        names = {n.strip() for n in known_names.split("\n") if n.strip()}
        problems = _dsl.validate_flow(ast, known_names=names or None)
        return json.dumps({
            "ast": ast.to_dict(),
            "atoms": [a.name for a in ast.iter_atoms()],
            "problems": problems,
        }, indent=2)

    @mcp.tool(
        name="kb_start_flow",
        description=(
            "Open a flow execution from a DSL string. Returns the flow "
            "id and the first set of pending steps. The AI client "
            "dispatches each pending atom (and surfaces gates as human "
            "prompts), then reports completion via kb_mark_step_done."
        ),
    )
    def _kb_start_flow(
        source: str,
        known_names: str = "",
        project_path: str = "",
        source_tool: str = "",
        source_session: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_flow_store(ctx)
        names = {n.strip() for n in known_names.split("\n") if n.strip()}
        flow = store.start(
            source=source,
            known_names=names or None,
            project_path=project_path,
            source_tool=source_tool,
            source_session=source_session,
        )
        return json.dumps({
            "flow": flow.to_dict(),
            "next_steps": [n.to_dict() for n in flow.next_steps()],
        }, indent=2)

    @mcp.tool(
        name="kb_get_next_steps",
        description=(
            "Read the pending steps of a flow. Each pending step is "
            "either an atom (the client should invoke the tool of that "
            "name) or a gate (the client should surface a human prompt). "
            "Empty list = flow finished."
        ),
    )
    def _kb_get_next_steps(
        flow_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_flow_store(ctx)
        flow = store.get(flow_id)
        if flow is None:
            raise ValueError(f"Flow {flow_id!r} not found")
        return json.dumps({
            "status": flow.status,
            "next_steps": [n.to_dict() for n in flow.next_steps()],
            "completed_count": len(flow.completed),
        }, indent=2)

    @mcp.tool(
        name="kb_mark_step_done",
        description=(
            "Mark one step of a flow as completed and advance the "
            "cursor. Idempotent on (flow_id, step_id). When the last "
            "step completes, status flips to 'completed' automatically."
        ),
    )
    def _kb_mark_step_done(
        flow_id: str,
        step_id: str,
        outputs: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_flow_store(ctx)
        outputs_dict = json.loads(outputs) if outputs else {}
        rec = store.mark_done(flow_id, step_id, outputs_dict)
        flow = store.get(flow_id)
        return json.dumps({
            "step": rec.to_dict(),
            "next_steps": [n.to_dict() for n in flow.next_steps()] if flow else [],
            "status": flow.status if flow else "unknown",
        }, indent=2)

    @mcp.tool(
        name="kb_get_flow",
        description="Read a flow execution by ID: AST, completed steps, status.",
    )
    def _kb_get_flow(
        flow_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_flow_store(ctx)
        flow = store.get(flow_id)
        if flow is None:
            raise ValueError(f"Flow {flow_id!r} not found")
        return json.dumps(flow.to_dict(), indent=2)

    @mcp.tool(
        name="kb_list_flows",
        description="List flow executions. Filter by status (open/completed/cancelled) or source_tool.",
    )
    def _kb_list_flows(
        status: str = "",
        source_tool: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        store = _get_flow_store(ctx)
        items = store.list_all(status=status, source_tool=source_tool)
        return json.dumps([f.to_dict() for f in items], indent=2)

    # ════════════════════════════════════════════════════════════════════
    # AgentRouter -- rank experts for a task by keyword overlap
    # ════════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="kb_route_experts",
        description=(
            "Rank expert YAML profiles by keyword overlap with a task "
            "description. Loads .yaml files from `experts_dir` and "
            "scores each by Jaccard similarity over name + description "
            "+ system_prompt + relevance_signals. No embedding model "
            "required. Returns at most `top_k` results above `min_score`."
        ),
    )
    def _kb_route_experts(
        task: str,
        experts_dir: str,
        top_k: int = 5,
        min_score: float = 0.05,
        ctx: Optional[Context] = None,
    ) -> str:
        from swarm_core.experts.registry import ExpertRegistry
        from swarm_core.experts.suggest import TaskSimilarityStrategy
        if not task:
            raise ValueError("task must be non-empty")
        ed = Path(experts_dir).expanduser()
        if not ed.is_dir():
            raise ValueError(f"experts_dir {experts_dir!r} is not a directory")
        registry = ExpertRegistry(
            builtin_dir=ed,
            suggest_strategy=TaskSimilarityStrategy(min_score=min_score),
        )
        ranked = registry.suggest(task)
        if top_k > 0:
            ranked = ranked[:top_k]
        return json.dumps({
            "task": task,
            "experts_dir": str(ed),
            "ranked": ranked,
            "total_loaded": len(registry.list_profiles()),
        }, indent=2)

    return mcp
