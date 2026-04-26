"""Stage-gate enforcement for `kb_advance_pipeline`.

Decision docs (e.g. `2026-04-26-stage-0a-idea-stage.md`) specify that
some pipeline stages must not advance until a content gate is satisfied:

  - Stage `idea`   -- the latest idea session must have status DESIGN_APPROVED.
  - Stage `plan`   -- the latest plan session must have status VALIDATED.
  - Stage `harden` -- the latest hardening session must have 0 blockers
                      OR the user explicitly forces.

Gates are intentionally *advisory* in code: they enforce by default but
the MCP `kb_advance_pipeline(force=True)` parameter overrides. This
matches Nielsen "user control and freedom" -- we suggest, not block.

PipelineManager itself stays content-agnostic; the gate-check happens
in the MCP-tool wrapper which calls `check_stage_gate` before
`pipe_mgr.advance()`.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import SuiteConfig

GateResult = tuple[bool, str]  # (ok, message)


def check_stage_gate(stage: str, config: SuiteConfig) -> GateResult:
    """Return (True, "") if the gate is satisfied, (False, hint) otherwise.

    Only enforces the three NEW stages (idea / plan / harden). Other
    stages (spec / arch / review / fix / verify / doc / release) return
    OK -- their existing tools manage their own progression and the
    pipeline.advance() call has been the only thing standing between
    them since before this gate layer existed.
    """
    if stage == "idea":
        return _check_idea_gate(config)
    if stage == "plan":
        return _check_plan_gate(config)
    if stage == "harden":
        return _check_harden_gate(config)
    return True, ""


# ---------------------------------------------------------------- per-stage


def _check_idea_gate(config: SuiteConfig) -> GateResult:
    """Idea -> next requires latest idea session has idea_status=design_approved."""
    sess_dir = _latest_session(config.tool_sessions_path("idea"))
    if sess_dir is None:
        return False, (
            "no Idea session found. Open one with kb_start_idea_session(...) "
            "and finalize a design before advancing, OR pass force=True to "
            "skip this stage entirely."
        )
    meta = _read_meta(sess_dir)
    status = meta.get("idea_status", "")
    if status != "design_approved":
        return False, (
            f"latest Idea session {sess_dir.name!r} has idea_status={status!r}, "
            f"expected 'design_approved'. Run kb_finalize_idea_design(...) "
            f"after the user approves the design, OR pass force=True."
        )
    return True, ""


def _check_plan_gate(config: SuiteConfig) -> GateResult:
    """Plan -> next requires latest plan session has plan_status=validated."""
    sess_dir = _latest_session(config.tool_sessions_path("plan"))
    if sess_dir is None:
        return False, (
            "no Plan session found. Open one with kb_start_plan_session(...) "
            "and finalize a plan before advancing, OR pass force=True to "
            "skip this stage entirely."
        )
    meta = _read_meta(sess_dir)
    status = meta.get("plan_status", "")
    if status != "validated":
        return False, (
            f"latest Plan session {sess_dir.name!r} has plan_status={status!r}, "
            f"expected 'validated'. Run kb_finalize_plan(...) and address "
            f"any validation errors, OR pass force=True."
        )
    return True, ""


def _check_harden_gate(config: SuiteConfig) -> GateResult:
    """Harden -> next requires latest hardening session has 0 blockers."""
    sess_dir = _latest_session(config.tool_sessions_path("harden"))
    if sess_dir is None:
        return False, (
            "no Hardening session found. Open one with kb_start_hardening(...) "
            "and run the checks before advancing to Release, OR pass "
            "force=True."
        )
    meta = _read_meta(sess_dir)
    blockers = sum(
        1 for r in (meta.get("check_results") or {}).values()
        if isinstance(r, dict) and r.get("installed", True) and not r.get("passed", True)
    )
    if blockers > 0:
        return False, (
            f"Hardening session {sess_dir.name!r} has {blockers} blocker(s). "
            f"Run kb_get_hardening_report(...) for detail and address each, "
            f"OR pass force=True if you accept the risk."
        )
    return True, ""


# ---------------------------------------------------------------- helpers


def _latest_session(sessions_root: Path) -> Path | None:
    """Return the most-recently-modified session dir in `sessions_root`,
    or None if the dir is empty / missing.
    """
    if not sessions_root.is_dir():
        return None
    sessions = [d for d in sessions_root.iterdir() if d.is_dir()]
    if not sessions:
        return None
    return max(sessions, key=lambda d: d.stat().st_mtime)


def _read_meta(sess_dir: Path) -> dict:
    meta_path = sess_dir / "meta.json"
    if not meta_path.is_file():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
