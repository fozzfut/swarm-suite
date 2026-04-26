"""kb_navigator_state -- single-call context snapshot for the navigator skill.

The `swarm_suite_navigator` skill (in swarm_core/skills/) instructs the AI
client to call this tool at session start (and again after any
state-changing action) so it has everything it needs to suggest 2-3
concrete next steps to the user without the user having to know any of
the 30+ underlying MCP tools.

Output is a compact JSON snapshot:
  * Active pipeline (if any) with current stage + per-stage status
  * Open composable artifacts (judgings, verifications, pgve, flows,
    debates) with just the IDs + minimum descriptors
  * Counts of recent findings + decisions for the project
  * STAGE_INFO actions for the current stage
  * `suggested_next_steps` -- 2-3 concrete options the navigator can
    present to the user, each with WHAT (action), WHY (state evidence),
    and `tools` (which MCP calls actually execute it)

The suggestions are derived from rule-based templates over the state
(no LLM call from inside this tool). The AI client adds the final
human-language framing using the navigator skill.

This is a READ-ONLY tool. Calling it never mutates state. Safe to call
at the start of every session and after every meaningful action.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .config import SuiteConfig
from .decision_store import DecisionStore
from .pipeline import STAGE_INFO, STAGE_ORDER, PipelineManager

_log = logging.getLogger("swarm_kb.navigator")


# Compact stage-status icons for the human-facing summary the navigator
# can echo back. Kept here (not in pipeline.py) because they're a
# presentation concern owned by the navigator surface.
_STAGE_GLYPH = {
    "completed": "[OK]",
    "active": "[..]",
    "skipped": "[--]",
    "pending": "[  ]",
}


def navigator_state(
    project_path: str,
    *,
    config: SuiteConfig | None = None,
    pipeline_manager: PipelineManager | None = None,
    decision_store: DecisionStore | None = None,
    judging_engine=None,
    verification_store=None,
    pgve_store=None,
    flow_store=None,
    debate_engine=None,
) -> dict:
    """Build the navigator-state snapshot for `project_path`.

    All store/engine arguments are injected (so swarm-kb's lifespan
    context can pass the singletons it already has). Each is optional;
    a missing engine just yields zero counts for its artifact kind.
    """
    cfg = config or SuiteConfig.load()

    # ---- Active pipeline -------------------------------------------------
    pipe_dict = _resolve_pipeline(project_path, pipeline_manager)

    # ---- Open composable artifacts (counts + thin summaries) -------------
    artifacts = {
        "judgings": _summarise_judgings(judging_engine, project_path),
        "verifications": _summarise_verifications(verification_store, project_path),
        "pgve": _summarise_pgve(pgve_store, project_path),
        "flows": _summarise_flows(flow_store, project_path),
        "debates": _summarise_debates(debate_engine, project_path),
    }

    # ---- Recent decisions ------------------------------------------------
    decisions = _recent_decisions(decision_store, project_path, limit=5)

    # ---- Current stage info ---------------------------------------------
    current_stage = pipe_dict.get("current_stage") if pipe_dict else None
    stage_info = _stage_info_for(current_stage)

    # ---- Suggested next steps -------------------------------------------
    suggestions = _derive_suggestions(
        project_path=project_path,
        pipeline=pipe_dict,
        artifacts=artifacts,
        recent_decisions=decisions,
    )

    return {
        "project_path": project_path,
        "active_pipeline": pipe_dict,
        "active_artifacts": artifacts,
        "recent_decisions": decisions,
        "current_stage_info": stage_info,
        "suggested_next_steps": suggestions,
    }


# ---------------------------------------------------------------------------
# Pipeline summary
# ---------------------------------------------------------------------------


def _resolve_pipeline(
    project_path: str, mgr: PipelineManager | None,
) -> Optional[dict]:
    if mgr is None:
        return None
    try:
        all_pipes = mgr.list_all()
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("Cannot list pipelines: %s", exc)
        return None
    matching = [p for p in all_pipes if p.project_path == project_path]
    if not matching:
        return None
    # Most-recently-created active pipeline wins; fall back to most recent.
    actives = [
        p for p in matching
        if p.stages.get(p.current_stage)
        and p.stages[p.current_stage].status == "active"
    ]
    pipe = (actives or matching)[-1]
    stages_view = {}
    for name in STAGE_ORDER:
        st = pipe.stages.get(name)
        if st is None:
            stages_view[name] = {"status": "pending", "glyph": "[  ]"}
        else:
            stages_view[name] = {
                "status": st.status,
                "glyph": _STAGE_GLYPH.get(st.status, "[??]"),
                "approved_findings": st.approved_findings,
                "dismissed_findings": st.dismissed_findings,
                "session_ids": list(st.session_ids),
            }
    next_stage = _next_stage(pipe.current_stage)
    return {
        "id": pipe.id,
        "current_stage": pipe.current_stage,
        "next_stage": next_stage,
        "current_stage_optional": _is_optional(pipe.current_stage),
        "next_stage_optional": _is_optional(next_stage) if next_stage else False,
        "stages": stages_view,
    }


def _next_stage(current: str) -> Optional[str]:
    try:
        idx = STAGE_ORDER.index(current)
    except ValueError:
        return None
    return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else None


def _is_optional(stage: str | None) -> bool:
    if stage is None:
        return False
    info = STAGE_INFO.get(stage, {})
    return bool(info.get("optional", False))


def _stage_info_for(stage: str | None) -> dict:
    if stage is None:
        return {}
    info = STAGE_INFO.get(stage, {})
    return {
        "name": info.get("name", stage),
        "tool": info.get("tool", ""),
        "description": info.get("description", ""),
        "actions": list(info.get("actions", [])),
        "optional": bool(info.get("optional", False)),
    }


# ---------------------------------------------------------------------------
# Artifact summaries (thin -- just enough for the navigator to refer to them)
# ---------------------------------------------------------------------------


def _summarise_judgings(eng, project_path: str) -> list[dict]:
    if eng is None:
        return []
    try:
        items = eng.list_all(status="open")
    except Exception:
        return []
    return [
        {
            "id": j.id,
            "subject": (j.subject[:80] + "...") if len(j.subject) > 80 else j.subject,
            "subject_kind": j.subject_kind,
            "covered_dimensions": len(j.covered_dimensions()),
            "total_dimensions": len(j.dimensions),
        }
        for j in items
        if not project_path or not j.project_path or j.project_path == project_path
    ]


def _summarise_verifications(store, project_path: str) -> list[dict]:
    if store is None:
        return []
    try:
        items = store.list_all(status="open")
    except Exception:
        return []
    return [
        {
            "id": r.id,
            "fix_session": r.fix_session,
            "evidence_count": len(r.evidence),
        }
        for r in items
        if not project_path or not r.project_path or r.project_path == project_path
    ]


def _summarise_pgve(store, project_path: str) -> list[dict]:
    if store is None:
        return []
    try:
        items = store.list_all(status="open")
    except Exception:
        return []
    return [
        {
            "id": s.id,
            "task_spec": (s.task_spec[:80] + "...") if len(s.task_spec) > 80 else s.task_spec,
            "candidates": len(s.candidates),
            "remaining_budget": s.remaining_budget(),
        }
        for s in items
        if not project_path or not s.project_path or s.project_path == project_path
    ]


def _summarise_flows(store, project_path: str) -> list[dict]:
    if store is None:
        return []
    try:
        items = store.list_all(status="open")
    except Exception:
        return []
    return [
        {
            "id": f.id,
            "source": (f.source[:80] + "...") if len(f.source) > 80 else f.source,
            "completed_steps": len(f.completed),
            "pending_steps": len(f.next_steps()),
        }
        for f in items
        if not project_path or not f.project_path or f.project_path == project_path
    ]


def _summarise_debates(engine, project_path: str) -> list[dict]:
    if engine is None:
        return []
    try:
        items = engine.list_debates(status="open")
    except Exception:
        return []
    return [
        {
            "id": d.id,
            "topic": (d.topic[:80] + "...") if len(d.topic) > 80 else d.topic,
            "format": d.format,
            "proposals": len(d.proposals),
        }
        for d in items
        if not project_path or not d.project_path or d.project_path == project_path
    ]


def _recent_decisions(
    store: DecisionStore | None, project_path: str, *, limit: int,
) -> list[dict]:
    if store is None:
        return []
    try:
        items = store.query(project_path=project_path)
    except Exception:
        return []
    items = sorted(items, key=lambda d: getattr(d, "created_at", ""), reverse=True)[:limit]
    return [
        {
            "id": d.id,
            "title": d.title,
            "status": d.status,
            "tags": list(getattr(d, "tags", []) or []),
        }
        for d in items
    ]


# ---------------------------------------------------------------------------
# Suggestion engine -- pure rules over state
# ---------------------------------------------------------------------------


def _derive_suggestions(
    *,
    project_path: str,
    pipeline: Optional[dict],
    artifacts: dict,
    recent_decisions: list[dict],
) -> list[dict]:
    """Rule-based 2-3 next-step suggestions for the navigator skill.

    Each suggestion is a dict the AI client can render with the skill:
        {label, why, tools, kind}
    `kind` lets the navigator group similar options ("continue" vs
    "diverge" vs "advance"). `tools` is the canonical MCP-call sequence
    if the user picks this option.
    """
    suggestions: list[dict] = []

    # --- No pipeline yet -------------------------------------------------
    if pipeline is None:
        suggestions.append({
            "kind": "start",
            "label": "Start a new pipeline for this project",
            "why": "No active pipeline found for this project_path.",
            "tools": ["kb_start_pipeline"],
            "needs_clarification": [
                "Is this a greenfield project (no codebase yet)?",
                "Is this embedded / firmware (datasheets to ingest)?",
            ],
        })
        return suggestions

    current = pipeline["current_stage"]
    nxt = pipeline.get("next_stage")

    # --- In-flight artifacts always offer continuation ------------------
    for j in artifacts.get("judgings", []):
        if j["covered_dimensions"] < j["total_dimensions"]:
            suggestions.append({
                "kind": "continue_artifact",
                "label": (
                    f"Continue judging {j['id']} -- "
                    f"{j['covered_dimensions']}/{j['total_dimensions']} dimensions covered"
                ),
                "why": "Open judging session has uncovered dimensions.",
                "tools": ["kb_judge_dimension", "kb_resolve_judging"],
            })

    for s in artifacts.get("pgve", []):
        if s["remaining_budget"] > 0:
            suggestions.append({
                "kind": "continue_artifact",
                "label": (
                    f"Continue PGVE session {s['id']} -- {s['candidates']} candidates so far, "
                    f"{s['remaining_budget']} attempts left"
                ),
                "why": f"Open generate-verify-retry loop on: {s['task_spec']}",
                "tools": ["kb_submit_candidate", "kb_evaluate_candidate"],
            })

    for r in artifacts.get("verifications", []):
        suggestions.append({
            "kind": "continue_artifact",
            "label": (
                f"Continue verification {r['id']} -- {r['evidence_count']} evidence pieces attached"
            ),
            "why": "Open verification report not yet finalised.",
            "tools": ["kb_add_verification_evidence", "kb_finalise_verification"],
        })

    for f in artifacts.get("flows", []):
        if f["pending_steps"] > 0:
            suggestions.append({
                "kind": "continue_artifact",
                "label": (
                    f"Continue flow {f['id']} -- {f['pending_steps']} steps pending "
                    f"({f['completed_steps']} done)"
                ),
                "why": f"Open flow source: {f['source']}",
                "tools": ["kb_get_next_steps", "kb_mark_step_done"],
            })

    for d in artifacts.get("debates", []):
        suggestions.append({
            "kind": "continue_artifact",
            "label": (
                f"Continue debate {d['id']} on '{d['topic']}' -- format={d['format']}, "
                f"{d['proposals']} proposals"
            ),
            "why": "Open debate has not been resolved.",
            "tools": ["kb_propose", "kb_critique", "kb_vote", "kb_resolve_debate"],
        })

    # --- Stage-driven defaults ------------------------------------------
    suggestions.extend(_stage_default_suggestions(current, nxt))

    # Cap at the most informative 4 to keep the navigator's options short.
    return suggestions[:4]


_STAGE_DEFAULTS: dict[str, list[dict]] = {
    "idea": [
        {
            "kind": "stage_continue",
            "label": "Drive the brainstorming skill -- one question at a time",
            "why": "Idea stage active; no design captured yet.",
            "tools": ["kb_capture_idea_answer", "kb_record_idea_alternatives",
                      "kb_finalize_idea_design"],
        },
    ],
    "spec": [
        {
            "kind": "stage_continue",
            "label": "Ingest a datasheet / spec document",
            "why": "Spec stage active; agent extracts hardware constraints.",
            "tools": ["spec_ingest", "spec_check_conflicts", "spec_export_for_arch"],
        },
    ],
    "arch": [
        {
            "kind": "stage_continue",
            "label": "Run architecture analysis on the project",
            "why": "Arch stage active; scan structural metrics + run any debates needed.",
            "tools": ["arch_analyze", "orchestrate_debate"],
        },
        {
            "kind": "diverge",
            "label": "Open a debate on a specific design question",
            "why": "Multi-agent debate produces a cleaner ADR than ad-hoc reasoning.",
            "tools": ["kb_list_debate_formats", "kb_get_debate_format",
                      "kb_start_debate"],
            "needs_clarification": ["What's the design question?"],
        },
    ],
    "plan": [
        {
            "kind": "stage_continue",
            "label": "Drive the writing_plans skill -- emit one 2-5 min task at a time",
            "why": "Plan stage active; convert ADRs to a TDD-grade executable plan.",
            "tools": ["kb_emit_task", "kb_finalize_plan"],
        },
    ],
    "review": [
        {
            "kind": "stage_continue",
            "label": "Orchestrate a multi-expert review",
            "why": "Review stage active; 13 experts ready to scan code.",
            "tools": ["orchestrate_review", "get_summary"],
        },
        {
            "kind": "diverge",
            "label": "Pre-pick the right experts for this task via AgentRouter",
            "why": "Avoid running every expert when a focused subset matters more.",
            "tools": ["kb_route_experts", "orchestrate_review"],
            "needs_clarification": ["What's the task or scope?"],
        },
    ],
    "fix": [
        {
            "kind": "stage_continue",
            "label": "Apply fixes for confirmed findings",
            "why": "Fix stage active; review findings ready to be fixed.",
            "tools": ["snapshot_tests", "fix_plan", "fix_apply",
                      "verify_fixes", "apply_approved",
                      "kb_check_quality_gate"],
        },
        {
            "kind": "diverge",
            "label": "Drive a generate-verify-retry loop for one tricky finding",
            "why": "PGVE shines when one-shot proposals keep failing review.",
            "tools": ["kb_start_pgve", "kb_submit_candidate", "kb_evaluate_candidate"],
            "needs_clarification": ["Which finding needs the retry loop?"],
        },
    ],
    "verify": [
        {
            "kind": "stage_continue",
            "label": "Run regression check + build a VerificationReport",
            "why": "Verify stage active; consolidate evidence before doc/release.",
            "tools": ["check_regression", "kb_check_quality_gate",
                      "kb_start_verification", "kb_add_verification_evidence",
                      "kb_finalise_verification"],
        },
    ],
    "doc": [
        {
            "kind": "stage_continue",
            "label": "Generate / verify project documentation",
            "why": "Doc stage active. NOTE: stage is OPTIONAL -- skip during iteration; run once near release.",
            "tools": ["doc_verify", "doc_generate"],
        },
        {
            "kind": "skip",
            "label": "Skip the doc stage (run it later, near release)",
            "why": "Doc is optional. Iterating on docs every fix cycle burns AI tokens; do it once when the code stabilises.",
            "tools": ["kb_skip_stage"],
        },
    ],
    "harden": [
        {
            "kind": "stage_continue",
            "label": "Run all hardening checks",
            "why": "Hardening stage active; last automated quality gate before release.",
            "tools": ["kb_start_hardening", "kb_run_check",
                      "kb_get_hardening_report"],
        },
    ],
    "release": [
        {
            "kind": "stage_continue",
            "label": "Prepare release artifacts (never auto-publishes)",
            "why": "Release stage active; bump version, draft changelog, build dist.",
            "tools": ["kb_start_release", "kb_propose_version_bump",
                      "kb_generate_changelog", "kb_validate_pyproject",
                      "kb_build_dist", "kb_release_summary"],
        },
    ],
}


def _stage_default_suggestions(
    current: str, nxt: Optional[str],
) -> list[dict]:
    """Stage-driven default suggestions + an "advance" option when sensible."""
    out: list[dict] = list(_STAGE_DEFAULTS.get(current, []))
    if nxt:
        skip_label = "Skip" if _is_optional(current) else "Advance"
        out.append({
            "kind": "advance",
            "label": (
                f"{skip_label} to next stage: {STAGE_INFO.get(nxt, {}).get('name', nxt)}"
                + (" (optional -- can also skip)" if _is_optional(nxt) else "")
            ),
            "why": (
                f"Current stage '{current}' has produced enough output to advance "
                f"to '{nxt}'. ALWAYS confirm with the user first."
            ),
            "tools": ["kb_advance_pipeline"],
        })
    return out
