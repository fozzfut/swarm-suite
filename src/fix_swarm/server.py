"""MCP Server for FixSwarm -- multi-agent fix collaboration tools."""

import json
import logging
from typing import Optional
from pathlib import Path
from datetime import datetime, timezone

from .models import (
    Event,
    EventType,
    FixProposal,
    Message,
    MessageType,
    ProposalStatus,
    Reaction,
    ReactionType,
)

_log = logging.getLogger("fix_swarm.server")

# ── Expert mapping: finding categories/tags → fix expert profiles ──

_EXPERT_MAP = {
    "security": "security-fix",
    "injection": "security-fix",
    "auth": "security-fix",
    "authentication": "security-fix",
    "authorization": "security-fix",
    "xss": "security-fix",
    "csrf": "security-fix",
    "sqli": "security-fix",
    "traversal": "security-fix",
    "performance": "performance-fix",
    "n+1": "performance-fix",
    "blocking": "performance-fix",
    "latency": "performance-fix",
    "memory-leak": "performance-fix",
    "cache": "performance-fix",
    "type-safety": "type-fix",
    "nullable": "type-fix",
    "type-error": "type-fix",
    "cast": "type-fix",
    "typing": "type-fix",
    "error-handling": "error-handling-fix",
    "swallowed": "error-handling-fix",
    "exception": "error-handling-fix",
    "unhandled": "error-handling-fix",
    "test": "test-fix",
    "assertion": "test-fix",
    "coverage": "test-fix",
    "mock": "test-fix",
    "dependency": "dependency-fix",
    "deprecated": "dependency-fix",
    "outdated": "dependency-fix",
    "vulnerability": "dependency-fix",
    "compatibility": "compatibility-fix",
    "compat": "compatibility-fix",
    "migration": "compatibility-fix",
    "backwards": "compatibility-fix",
    "architecture": "refactoring",
    "coupling": "refactoring",
    "circular-dependency": "refactoring",
    "complexity": "refactoring",
    "bloated-module": "refactoring",
    "instability": "refactoring",
    "modularity": "refactoring",
    "srp": "refactoring",
    "arch-decision": "refactoring",
    "bottleneck": "performance-fix",
}


def _map_to_expert(category: str, tags: list) -> str:
    """Map a finding category and tags to the best fix expert profile."""
    cat_lower = category.lower().strip()
    if cat_lower in _EXPERT_MAP:
        return _EXPERT_MAP[cat_lower]
    for tag in tags:
        tag_lower = tag.lower().strip()
        if tag_lower in _EXPERT_MAP:
            return _EXPERT_MAP[tag_lower]
    # Substring matching as fallback
    for key, expert in _EXPERT_MAP.items():
        if key in cat_lower:
            return expert
        for tag in tags:
            if key in tag.lower():
                return expert
    return "refactoring"


def _ok(data: dict) -> str:
    return json.dumps(data)


def _err(message: str) -> str:
    return json.dumps({"error": message})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_mcp_server():
    """Create and configure the FixSwarm MCP server with multi-agent collaboration tools."""
    from mcp.server.fastmcp import FastMCP, Context
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
        from .session_manager import FixSessionManager
        fix_dir = Path("~/.swarm-kb/fix/sessions").expanduser()
        fix_dir.mkdir(parents=True, exist_ok=True)
        mgr = FixSessionManager(fix_dir)
        yield {"manager": mgr}

    def _get_mgr(ctx: Optional[Context]):
        assert ctx is not None
        return ctx.request_context.lifespan_context["manager"]

    mcp = FastMCP("FixSwarm", lifespan=lifespan)

    # ═══════════════════════════════════════════════════════════════════
    # Session Management
    # ═══════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="start_session",
        description="Start a multi-agent fix session from a review session, arch session, or report.",
    )
    def _start_session(
        review_session: str = "",
        arch_session: str = "",
        project_path: str = ".",
        name: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            session_id = mgr.start_session(
                project_path=project_path,
                name=name or None,
                review_session=review_session,
            )

            # Load findings from review session if provided
            finding_count = 0
            arch_finding_count = 0
            if review_session:
                try:
                    findings = _load_findings_from_review(review_session)
                    for f in findings:
                        mgr.add_finding(session_id, f)
                    finding_count = len(findings)
                except Exception as exc:
                    _log.warning("Failed to load findings from review session %s: %s", review_session, exc)

            # Load findings from arch debate session if provided
            if arch_session:
                arch_findings = []
                try:
                    from swarm_kb.finding_reader import FindingReader
                    from swarm_kb.config import SuiteConfig
                    config = SuiteConfig.load()
                    arch_reader = FindingReader(config.tool_sessions_path("arch") / arch_session)
                    if arch_reader.exists():
                        arch_findings = arch_reader.search(status="open")
                except ImportError:
                    arch_findings = []
                except Exception as exc:
                    _log.warning("swarm-kb arch finding lookup failed for %s: %s", arch_session, exc)
                    arch_findings = []

                # Fallback to arch_adapter if swarm-kb returned nothing
                if not arch_findings:
                    try:
                        from .arch_adapter import extract_debate_findings
                        adapter_findings = extract_debate_findings(arch_session)
                        for af in adapter_findings:
                            arch_findings.append(af.to_finding_dict())
                    except Exception as exc:
                        _log.warning("arch_adapter fallback failed for %s: %s", arch_session, exc)

                for af in arch_findings:
                    mgr.add_finding(session_id, af if isinstance(af, dict) else af.to_finding_dict())
                arch_finding_count += len(arch_findings)

            # Search for arch findings when no review source is given
            if project_path and not review_session:
                arch_findings = []
                try:
                    from swarm_kb.finding_reader import search_all_findings
                    from swarm_kb.config import SuiteConfig
                    config = SuiteConfig.load()
                    arch_findings = search_all_findings(config, tool="arch", status="open")
                except (ImportError, Exception):
                    arch_findings = []

                # Fallback to arch_adapter if swarm-kb returned nothing
                if not arch_findings:
                    try:
                        from .arch_adapter import analyze_project_for_arch_findings
                        adapter_findings = analyze_project_for_arch_findings(project_path)
                        for af in adapter_findings:
                            arch_findings.append(af.to_finding_dict())
                    except Exception as exc:
                        _log.warning("arch_adapter fallback failed for %s: %s", project_path, exc)

                for af in arch_findings:
                    mgr.add_finding(session_id, af if isinstance(af, dict) else af.to_finding_dict())
                arch_finding_count += len(arch_findings)

            return _ok({
                "session_id": session_id,
                "review_session": review_session,
                "arch_session": arch_session,
                "project_path": project_path,
                "finding_count": finding_count,
                "arch_finding_count": arch_finding_count,
                "status": "active",
            })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="end_session",
        description="End fix session and generate summary report.",
    )
    def _end_session(
        session_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            result = mgr.end_session(session_id)
            return _ok(result)
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="get_session",
        description="Get fix session status and statistics.",
    )
    def _get_session(
        session_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            result = mgr.get_session(session_id)
            return _ok(result)
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="list_sessions",
        description="List all fix sessions.",
    )
    def _list_sessions(
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            sessions = mgr.list_sessions()
            return _ok({"sessions": sessions})
        except Exception as exc:
            return _err(str(exc))

    # ═══════════════════════════════════════════════════════════════════
    # Expert Coordination
    # ═══════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="suggest_experts",
        description="Analyze findings and recommend fix expert profiles.",
    )
    def _suggest_experts(
        session_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            findings = mgr.get_findings(session_id)

            if not findings:
                return _ok({"experts": [], "message": "No findings to analyze"})

            # Count categories and map to experts
            expert_counts: dict[str, int] = {}
            expert_findings: dict[str, list[str]] = {}
            for f in findings:
                category = f.get("category", "")
                tags = f.get("tags", [])
                expert = _map_to_expert(category, tags)
                expert_counts[expert] = expert_counts.get(expert, 0) + 1
                if expert not in expert_findings:
                    expert_findings[expert] = []
                expert_findings[expert].append(f.get("id", ""))

            # Ensure "refactoring" expert is included when arch findings are present
            has_arch_findings = any(
                "architecture" in f.get("category", "").lower()
                or "architecture" in [t.lower() for t in f.get("tags", [])]
                or "refactoring" in [t.lower() for t in f.get("tags", [])]
                for f in findings
            )
            if has_arch_findings and "refactoring" not in expert_counts:
                expert_counts["refactoring"] = 0
                expert_findings["refactoring"] = []

            # Build recommendations sorted by finding count (descending)
            recommendations = []
            for expert, count in sorted(expert_counts.items(), key=lambda x: -x[1]):
                recommendations.append({
                    "expert_role": expert,
                    "finding_count": count,
                    "finding_ids": expert_findings[expert],
                    "priority": "high" if count >= 3 else ("medium" if count >= 1 else "low"),
                })

            return _ok({
                "session_id": session_id,
                "total_findings": len(findings),
                "experts": recommendations,
            })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="claim_finding",
        description="Claim a finding for fixing. Prevents duplicate work.",
    )
    def _claim_finding(
        session_id: str,
        finding_id: str,
        expert_role: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            result = mgr.claim_finding(session_id, finding_id, expert_role)
            return _ok(result)
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="release_finding",
        description="Release a claimed finding.",
    )
    def _release_finding(
        session_id: str,
        finding_id: str,
        expert_role: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            result = mgr.release_finding(session_id, finding_id, expert_role)
            return _ok(result)
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="get_claims",
        description="See which findings are claimed by which experts.",
    )
    def _get_claims(
        session_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            claims = mgr.get_claims(session_id)
            return _ok({"session_id": session_id, "claims": claims})
        except Exception as exc:
            return _err(str(exc))

    # ═══════════════════════════════════════════════════════════════════
    # Fix Proposals
    # ═══════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="propose_fix",
        description="Propose a fix for a finding. Other experts can review before it's applied.",
    )
    def _propose_fix(
        session_id: str,
        expert_role: str,
        finding_id: str,
        file: str,
        line_start: int,
        line_end: int,
        old_text: str,
        new_text: str,
        rationale: str,
        confidence: float = 0.8,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            proposal = FixProposal(
                expert_role=expert_role,
                finding_id=finding_id,
                file=file,
                line_start=line_start,
                line_end=line_end,
                old_text=old_text,
                new_text=new_text,
                rationale=rationale,
                confidence=confidence,
            )

            proposal_id = mgr.add_proposal(session_id, proposal)

            return _ok({
                "proposal_id": proposal_id,
                "status": "proposed",
                "finding_id": finding_id,
                "file": file,
            })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="get_proposals",
        description="Get fix proposals. Filter by status, expert, or file.",
    )
    def _get_proposals(
        session_id: str,
        status: str = "",
        expert_role: str = "",
        file: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            proposals = mgr.get_proposals(session_id)

            # Apply filters
            if status:
                proposals = [p for p in proposals if p.get("status", "") == status.lower()]
            if expert_role:
                proposals = [p for p in proposals if p.get("expert_role", "") == expert_role]
            if file:
                proposals = [p for p in proposals if p.get("file", "") == file]

            return _ok({
                "session_id": session_id,
                "count": len(proposals),
                "proposals": proposals,
            })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="react",
        description="React to a fix proposal: approve, reject, or suggest alternative.",
    )
    def _react(
        session_id: str,
        proposal_id: str,
        expert_role: str,
        reaction_type: str,
        comment: str = "",
        alternative_text: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            rt = reaction_type.lower().strip()
            rt_map = {
                "approve": ReactionType.APPROVE,
                "reject": ReactionType.REJECT,
                "suggest": ReactionType.SUGGEST_ALTERNATIVE,
                "suggest_alternative": ReactionType.SUGGEST_ALTERNATIVE,
                "request_evidence": ReactionType.REQUEST_EVIDENCE,
            }
            if rt not in rt_map:
                return _err(f"Invalid reaction_type: {reaction_type}. Must be approve, reject, or suggest.")

            reaction = Reaction(
                expert=expert_role,
                reaction_type=rt_map[rt],
                comment=comment,
                alternative_text=alternative_text,
            )

            # add_reaction handles consensus check internally
            result = mgr.add_reaction(session_id, proposal_id, reaction)

            if not result.get("ok"):
                return _err(result.get("error", "Unknown error"))

            # Read back the proposal status after consensus check
            proposal = result.get("proposal", {})
            consensus = result.get("consensus", {})

            return _ok({
                "proposal_id": proposal_id,
                "proposal_status": proposal.get("status", "proposed"),
                "consensus": consensus,
            })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="get_proposal_reactions",
        description="Get all reactions on a fix proposal.",
    )
    def _get_proposal_reactions(
        session_id: str,
        proposal_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            proposal = mgr.get_proposal_by_id(session_id, proposal_id)
            if proposal is None:
                return _err(f"Proposal {proposal_id} not found")

            reactions = proposal.get("reactions", [])
            approvals = sum(1 for r in reactions if r.get("reaction_type") == "approve")
            rejections = sum(1 for r in reactions if r.get("reaction_type") == "reject")
            suggestions = sum(1 for r in reactions if r.get("reaction_type") == "suggest")

            return _ok({
                "proposal_id": proposal_id,
                "reactions": reactions,
                "summary": {
                    "approvals": approvals,
                    "rejections": rejections,
                    "suggestions": suggestions,
                    "total": len(reactions),
                },
            })
        except Exception as exc:
            return _err(str(exc))

    # ═══════════════════════════════════════════════════════════════════
    # Execution
    # ═══════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="apply_approved",
        description="Apply all approved fix proposals. Only applies proposals with status=approved.",
    )
    def _apply_approved(
        session_id: str,
        base_dir: str = ".",
        backup: bool = False,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            from .models import FixAction, FixActionType, FixPlan
            from .fix_applier import apply_plan

            mgr = _get_mgr(ctx)
            proposals = mgr.get_proposals(session_id)
            approved = [p for p in proposals if p.get("status") == "approved"]

            if not approved:
                return _ok({"status": "no_approved", "message": "No approved proposals to apply"})

            # Convert proposals to FixActions
            actions = []
            for p in approved:
                old_text = p.get("old_text", "")
                new_text = p.get("new_text", "")
                if not new_text.strip() and not old_text.strip():
                    continue
                if not old_text.strip():
                    action_type = FixActionType.INSERT
                elif not new_text.strip():
                    action_type = FixActionType.DELETE
                else:
                    action_type = FixActionType.REPLACE

                actions.append(FixAction(
                    finding_id=p.get("finding_id", p["proposal_id"]),
                    file=p["file"],
                    line_start=p["line_start"],
                    line_end=p["line_end"],
                    action=action_type,
                    old_text=old_text,
                    new_text=new_text,
                    rationale=p.get("rationale", ""),
                ))

            if not actions:
                return _ok({"status": "no_actions", "message": "Approved proposals produced no actionable fixes"})

            plan = FixPlan(actions=actions)
            results = apply_plan(plan, base_dir=base_dir, backup=backup)

            # Update proposal statuses based on results
            result_by_finding = {r.finding_id: r for r in results}
            applied_count = 0
            failed_count = 0
            for p in approved:
                fid = p.get("finding_id", p["proposal_id"])
                r = result_by_finding.get(fid)
                if r and r.success:
                    mgr.update_proposal_status(session_id, p["proposal_id"], ProposalStatus.APPLIED)
                    applied_count += 1
                elif r:
                    mgr.update_proposal_status(session_id, p["proposal_id"], ProposalStatus.FAILED)
                    failed_count += 1

            # Auto-check syntax on modified files
            syntax_errors = []
            try:
                from .regression_checker import check_syntax as _check_syn
                modified_files = list({p["file"] for p in approved if result_by_finding.get(p.get("finding_id", p["proposal_id"])) and result_by_finding[p.get("finding_id", p["proposal_id"])].success})
                if modified_files:
                    syntax_errors = _check_syn(modified_files, base_dir)
            except Exception as syn_exc:
                _log.warning("Post-apply syntax check failed: %s", syn_exc)

            return _ok({
                "status": "completed",
                "applied": applied_count,
                "failed": failed_count,
                "results": [r.to_dict() for r in results],
                "syntax_errors": syntax_errors,
            })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="apply_single",
        description="Apply a single fix proposal (bypasses consensus for expert override).",
    )
    def _apply_single(
        session_id: str,
        proposal_id: str,
        base_dir: str = ".",
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            from .models import FixAction, FixActionType, FixPlan
            from .fix_applier import apply_plan

            mgr = _get_mgr(ctx)
            proposal = mgr.get_proposal_by_id(session_id, proposal_id)
            if proposal is None:
                return _err(f"Proposal {proposal_id} not found")

            old_text = proposal.get("old_text", "")
            new_text = proposal.get("new_text", "")
            if not old_text.strip():
                action_type = FixActionType.INSERT
            elif not new_text.strip():
                action_type = FixActionType.DELETE
            else:
                action_type = FixActionType.REPLACE

            action = FixAction(
                finding_id=proposal.get("finding_id", proposal_id),
                file=proposal["file"],
                line_start=proposal["line_start"],
                line_end=proposal["line_end"],
                action=action_type,
                old_text=old_text,
                new_text=new_text,
                rationale=proposal.get("rationale", ""),
            )

            plan = FixPlan(actions=[action])
            results = apply_plan(plan, base_dir=base_dir)

            if results and results[0].success:
                mgr.update_proposal_status(session_id, proposal_id, ProposalStatus.APPLIED)
                return _ok({
                    "status": "applied",
                    "proposal_id": proposal_id,
                    "result": results[0].to_dict(),
                })
            else:
                error_msg = results[0].error if results else "No result returned"
                mgr.update_proposal_status(session_id, proposal_id, ProposalStatus.FAILED)
                return _ok({
                    "status": "failed",
                    "proposal_id": proposal_id,
                    "error": error_msg,
                })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="verify_fixes",
        description="Verify that applied fixes are correct.",
    )
    def _verify_fixes(
        session_id: str,
        base_dir: str = ".",
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            from .models import FixAction, FixActionType, FixPlan
            from .fix_applier import verify_fixes as _verify

            mgr = _get_mgr(ctx)
            proposals = mgr.get_proposals(session_id)
            applied = [p for p in proposals if p.get("status") == "applied"]

            if not applied:
                return _ok({"status": "nothing_to_verify", "message": "No applied proposals to verify"})

            # Build plan from applied proposals
            actions = []
            for p in applied:
                old_text = p.get("old_text", "")
                new_text = p.get("new_text", "")
                if not old_text.strip():
                    action_type = FixActionType.INSERT
                elif not new_text.strip():
                    action_type = FixActionType.DELETE
                else:
                    action_type = FixActionType.REPLACE

                actions.append(FixAction(
                    finding_id=p.get("finding_id", p["proposal_id"]),
                    file=p["file"],
                    line_start=p["line_start"],
                    line_end=p["line_end"],
                    action=action_type,
                    old_text=old_text,
                    new_text=new_text,
                    rationale=p.get("rationale", ""),
                ))

            plan = FixPlan(actions=actions)
            results = _verify(plan, base_dir=base_dir)

            passed = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success)

            # Update proposal statuses for verified fixes
            result_by_finding = {r.finding_id: r for r in results}
            for p in applied:
                fid = p.get("finding_id", p["proposal_id"])
                r = result_by_finding.get(fid)
                if r and r.success:
                    mgr.update_proposal_status(session_id, p["proposal_id"], ProposalStatus.VERIFIED)

            mgr.post_event(session_id, Event(
                event_type=EventType.VERIFICATION_COMPLETE,
                payload={"passed": passed, "failed": failed},
            ))

            return _ok({
                "status": "verified",
                "passed": passed,
                "failed": failed,
                "results": [r.to_dict() for r in results],
            })
        except Exception as exc:
            return _err(str(exc))

    # ═══════════════════════════════════════════════════════════════════
    # Messaging
    # ═══════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="send_message",
        description="Send a message to another fix expert.",
    )
    def _send_message(
        session_id: str,
        sender: str,
        recipient: str,
        content: str,
        context_id: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            msg = Message(
                sender=sender,
                recipient=recipient,
                msg_type=MessageType.DIRECT,
                content=content,
                context_id=context_id,
            )
            message_id = mgr.add_message(session_id, msg)

            return _ok({
                "message_id": message_id,
                "sender": sender,
                "recipient": recipient,
            })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="get_inbox",
        description="Get pending messages for a fix expert.",
    )
    def _get_inbox(
        session_id: str,
        expert_role: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            messages = mgr.get_messages(session_id, recipient=expert_role)

            # Mark messages as read
            for m in messages:
                mgr.mark_message_read(session_id, m.get("id", ""))

            return _ok({
                "expert_role": expert_role,
                "count": len(messages),
                "messages": messages,
            })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="broadcast",
        description="Broadcast a message to all fix experts.",
    )
    def _broadcast(
        session_id: str,
        sender: str,
        content: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            message_id = mgr.broadcast(session_id, sender, content)

            return _ok({
                "message_id": message_id,
                "sender": sender,
                "recipient": "all",
            })
        except Exception as exc:
            return _err(str(exc))

    # ═══════════════════════════════════════════════════════════════════
    # Phase Coordination
    # ═══════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="mark_phase_done",
        description="Mark that an expert has completed a phase (1=analyze, 2=cross-review, 3=apply).",
    )
    def _mark_phase_done(
        session_id: str,
        expert_role: str,
        phase: int,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            if phase not in (1, 2, 3):
                return _err(f"Invalid phase: {phase}. Must be 1 (analyze), 2 (cross-review), or 3 (apply).")

            phase_names = {1: "analyze", 2: "cross-review", 3: "apply"}
            mgr = _get_mgr(ctx)
            mgr.mark_phase_done(session_id, expert_role, phase)

            mgr.post_event(session_id, Event(
                event_type=EventType.PHASE_DONE,
                payload={
                    "expert_role": expert_role,
                    "phase": phase,
                    "phase_name": phase_names[phase],
                },
            ))

            return _ok({
                "session_id": session_id,
                "expert_role": expert_role,
                "phase": phase,
                "phase_name": phase_names[phase],
                "marked": True,
            })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="check_phase_ready",
        description="Check if all experts are done with a phase.",
    )
    def _check_phase_ready(
        session_id: str,
        phase: int,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            if phase not in (1, 2, 3):
                return _err(f"Invalid phase: {phase}. Must be 1 (analyze), 2 (cross-review), or 3 (apply).")

            phase_names = {1: "analyze", 2: "cross-review", 3: "apply"}
            mgr = _get_mgr(ctx)
            phase_data = mgr.get_phase_data(session_id)
            claims = mgr.get_claims(session_id)

            # Determine known experts from claims
            known_experts = set()
            for c in claims:
                known_experts.add(c.get("expert_role", ""))
            known_experts.discard("")

            # Check which experts have completed this phase
            phase_key = str(phase)
            completed_experts = set()
            if phase_key in phase_data:
                completed_experts = set(phase_data[phase_key])

            pending_experts = known_experts - completed_experts

            all_ready = len(known_experts) > 0 and len(pending_experts) == 0

            return _ok({
                "session_id": session_id,
                "phase": phase,
                "phase_name": phase_names[phase],
                "all_ready": all_ready,
                "completed": sorted(completed_experts),
                "pending": sorted(pending_experts),
                "total_experts": len(known_experts),
            })
        except Exception as exc:
            return _err(str(exc))

    # ═══════════════════════════════════════════════════════════════════
    # Reporting
    # ═══════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="get_summary",
        description="Get fix session summary: proposals by status, reactions, applied fixes.",
    )
    def _get_summary(
        session_id: str,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            session = mgr.get_session(session_id)
            proposals = mgr.get_proposals(session_id)
            findings = mgr.get_findings(session_id)
            claims = mgr.get_claims(session_id)

            # Count proposals by status
            by_status: dict[str, int] = {}
            total_reactions = 0
            total_approvals = 0
            total_rejections = 0
            files_touched: set = set()
            for p in proposals:
                st = p.get("status", "proposed")
                by_status[st] = by_status.get(st, 0) + 1
                reactions = p.get("reactions", [])
                total_reactions += len(reactions)
                total_approvals += sum(1 for r in reactions if r.get("reaction_type") == "approve")
                total_rejections += sum(1 for r in reactions if r.get("reaction_type") == "reject")
                files_touched.add(p.get("file", ""))
            files_touched.discard("")

            # Count findings by severity
            by_severity: dict[str, int] = {}
            for f in findings:
                sev = f.get("severity", "medium")
                by_severity[sev] = by_severity.get(sev, 0) + 1

            return _ok({
                "session_id": session_id,
                "status": session.get("status", "unknown"),
                "created_at": session.get("created_at", ""),
                "findings": {
                    "total": len(findings),
                    "by_severity": by_severity,
                },
                "proposals": {
                    "total": len(proposals),
                    "by_status": by_status,
                },
                "reactions": {
                    "total": total_reactions,
                    "approvals": total_approvals,
                    "rejections": total_rejections,
                },
                "claims": {
                    "total": len(claims),
                },
                "files_touched": sorted(files_touched),
            })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="get_events",
        description="Get session events for real-time tracking.",
    )
    def _get_events(
        session_id: str,
        after: int = 0,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            mgr = _get_mgr(ctx)
            events = mgr.get_events(session_id)

            # Filter events after the given sequence number
            if after > 0:
                events = events[after:]

            return _ok({
                "session_id": session_id,
                "count": len(events),
                "next_after": after + len(events),
                "events": events,
            })
        except Exception as exc:
            return _err(str(exc))

    # ═══════════════════════════════════════════════════════════════════
    # Legacy compatibility
    # ═══════════════════════════════════════════════════════════════════

    @mcp.tool(
        name="fix_plan",
        description="(Legacy) Parse report and show fix plan without collaboration.",
    )
    def _fix_plan(
        report: str = "",
        review_session: str = "",
        threshold: str = "medium",
        base_dir: str = ".",
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            from .models import Severity
            from .fix_planner import build_plan

            sev = Severity(threshold.lower())
            findings = _load_findings(report, review_session, sev)

            if not findings:
                return _ok({"status": "no_findings", "message": "No findings matched threshold"})

            fix_plan = build_plan(findings, base_dir=base_dir)

            if not fix_plan.actions:
                return _ok({"status": "no_actions", "message": "No actionable fixes"})

            return _ok({
                "findings": len(findings),
                "actions": len(fix_plan.actions),
                "files": fix_plan.files(),
                "plan": fix_plan.to_dict(),
            })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="fix_apply",
        description="(Legacy) Apply fixes from report without collaboration.",
    )
    def _fix_apply(
        report: str = "",
        review_session: str = "",
        threshold: str = "medium",
        base_dir: str = ".",
        backup: bool = False,
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            from .models import Severity
            from .fix_planner import build_plan
            from .fix_applier import apply_plan

            sev = Severity(threshold.lower())
            findings = _load_findings(report, review_session, sev)

            if not findings:
                return _ok({"status": "no_findings"})

            fix_plan = build_plan(findings, base_dir=base_dir)

            if not fix_plan.actions:
                return _ok({"status": "no_actions"})

            results = apply_plan(fix_plan, base_dir=base_dir, backup=backup)

            ok_count = sum(1 for r in results if r.success)
            fail_count = sum(1 for r in results if not r.success)

            # Create fix session in KB
            mgr = _get_mgr(ctx)
            fix_dir = mgr.sessions_dir
            session_id = _create_fix_session(
                fix_dir,
                review_session=review_session,
                report_path=report,
                fix_plan=fix_plan,
                results=results,
            )

            # Write xrefs and mark findings fixed in review session
            if review_session:
                _write_xrefs_and_mark_fixed(session_id, review_session, results)

            return _ok({
                "session_id": session_id,
                "succeeded": ok_count,
                "failed": fail_count,
                "results": [r.to_dict() for r in results],
            })
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(
        name="fix_verify",
        description="(Legacy) Verify fixes from report without collaboration.",
    )
    def _fix_verify(
        report: str = "",
        review_session: str = "",
        threshold: str = "medium",
        base_dir: str = ".",
        ctx: Optional[Context] = None,
    ) -> str:
        try:
            from .models import Severity
            from .fix_planner import build_plan
            from .fix_applier import verify_fixes

            sev = Severity(threshold.lower())
            findings = _load_findings(report, review_session, sev)

            if not findings:
                return _ok({"status": "no_findings"})

            fix_plan = build_plan(findings, base_dir=base_dir)

            if not fix_plan.actions:
                return _ok({"status": "no_actions"})

            results = verify_fixes(fix_plan, base_dir=base_dir)
            ok_count = sum(1 for r in results if r.success)
            fail_count = sum(1 for r in results if not r.success)

            return _ok({
                "passed": ok_count,
                "failed": fail_count,
                "results": [r.to_dict() for r in results],
            })
        except Exception as exc:
            return _err(str(exc))

    # ═══════════════════════════════════════════════════════════════════
    # Knowledge Base Integration
    # ═══════════════════════════════════════════════════════════════════

    @mcp.tool(name="load_decisions", description="Load active architectural decisions to guide fix strategy.")
    def _load_decisions(session_id: str = "", project_path: str = "", ctx: Optional[Context] = None) -> str:
        try:
            from swarm_kb.decision_store import DecisionStore
            from swarm_kb.config import SuiteConfig
            config = SuiteConfig.load()
            store = DecisionStore(config.decisions_path / "decisions.jsonl")
            decisions = store.query(status="accepted", project_path=project_path)
            return json.dumps([d.to_dict() for d in decisions])
        except (ImportError, Exception) as exc:
            return json.dumps({"error": f"Cannot load decisions: {exc}"})

    @mcp.tool(name="load_debates", description="Load debate history for context on architectural decisions.")
    def _load_debates(project_path: str = "", status: str = "", ctx: Optional[Context] = None) -> str:
        try:
            from swarm_kb.debate_store import DebateStore
            from swarm_kb.config import SuiteConfig
            config = SuiteConfig.load()
            store = DebateStore(config.debates_path / "debates.jsonl")
            debates = store.query(status=status, project_path=project_path)
            return json.dumps([d.to_dict() for d in debates])
        except (ImportError, Exception) as exc:
            return json.dumps({"error": f"Cannot load debates: {exc}"})

    # ═══════════════════════════════════════════════════════════════════
    # Regression Checking
    # ═══════════════════════════════════════════════════════════════════

    @mcp.tool(name="snapshot_tests", description="Run tests and save as 'before' baseline. Call BEFORE applying fixes.")
    def _snapshot_tests(session_id: str, base_dir: str = ".", test_command: str = "", ctx: Optional[Context] = None) -> str:
        try:
            from .regression_checker import run_tests
            mgr = _get_mgr(ctx)
            result = run_tests(test_command=test_command, base_dir=base_dir)
            # Store in session
            with mgr._lock:
                if session_id in mgr._sessions:
                    mgr._sessions[session_id]["tests_before"] = result.to_dict()
                    mgr._save_session(session_id)
            return _ok({"status": "snapshot_saved", "tests_passed": result.passed, **result.to_dict()})
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(name="run_tests", description="Run project test suite. Auto-detects pytest/npm/go/cargo.")
    def _run_tests(base_dir: str = ".", test_command: str = "", ctx: Optional[Context] = None) -> str:
        try:
            from .regression_checker import run_tests
            result = run_tests(test_command=test_command, base_dir=base_dir)
            return _ok(result.to_dict())
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(name="check_regression", description="Full regression check on applied fixes: syntax validation, test comparison, re-scan. Call AFTER applying fixes.")
    def _check_regression(session_id: str, base_dir: str = ".", test_command: str = "", ctx: Optional[Context] = None) -> str:
        try:
            from .regression_checker import check_regression
            mgr = _get_mgr(ctx)

            # Get modified files from applied proposals
            proposals = mgr.get_proposals(session_id, status="applied")
            modified_files = list({p["file"] for p in proposals})

            if not modified_files:
                return _ok({"status": "no_applied_fixes", "overall_ok": True})

            # Get pre-fix test baseline
            session = mgr.get_session(session_id)
            tests_before = session.get("tests_before")

            report = check_regression(
                modified_files=modified_files,
                base_dir=base_dir,
                test_command=test_command,
                tests_before=tests_before,
            )

            return _ok(report.to_dict())
        except Exception as exc:
            return _err(str(exc))

    @mcp.tool(name="check_syntax", description="Quick syntax check on specific files. Use after individual fix application.")
    def _check_syntax(files: str, base_dir: str = ".", ctx: Optional[Context] = None) -> str:
        try:
            from .regression_checker import check_syntax
            file_list = [f.strip() for f in files.split(",") if f.strip()]
            errors = check_syntax(file_list, base_dir)
            return _ok({"ok": len(errors) == 0, "errors": errors})
        except Exception as exc:
            return _err(str(exc))

    return mcp


# ═══════════════════════════════════════════════════════════════════════
# Module-level helpers (shared by legacy and new tools)
# ═══════════════════════════════════════════════════════════════════════


def _load_findings_from_review(review_session: str) -> list:
    """Load findings from a review session in KB and return as dicts."""
    try:
        from swarm_kb.finding_reader import get_finding_reader
        reader = get_finding_reader(review_session)
        if not reader.exists():
            return []
        all_findings = reader.search(status="open")
        return all_findings
    except ImportError:
        _log.warning("swarm_kb not available; cannot load from review session")
        return []
    except Exception as exc:
        _log.warning("Failed to load findings from review session %s: %s", review_session, exc)
        return []


def _load_findings(report: str, review_session: str, threshold):
    """Load findings from either a report file or a review session in KB."""
    if review_session:
        from swarm_kb.finding_reader import get_finding_reader
        reader = get_finding_reader(review_session)
        if not reader.exists():
            return []
        all_findings = reader.search(status="open")
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
        _log.warning("Failed to write xrefs/mark fixed: %s", exc)
