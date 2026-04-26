"""Stage 0a Idea -- captures brainstorming output.

Drives the `brainstorming` skill (in swarm_core/skills/) through four
phases: Q&A, alternatives, design presentation, planning handoff.
Stores the artifacts so the next pipeline stage (Architecture) can pick
them up.

See docs/decisions/2026-04-26-stage-0a-idea-stage.md for the contract.
"""

from __future__ import annotations

import json
from pathlib import Path

from swarm_core.io import atomic_write_text, append_jsonl_line
from swarm_core.logging_setup import get_logger
from swarm_core.sessions import SessionLifecycle
from swarm_core.timeutil import now_iso

_log = get_logger("kb.idea_session")


class IdeaStatus:
    """Lifecycle states for an Idea session.

    Lives as a string enum (no `enum.Enum`) so the values appear unchanged
    in meta.json and survive cross-version reads.
    """
    GATHERING = "gathering"          # Phase 1: Q&A
    EXPLORING = "exploring"          # Phase 2: alternatives
    DESIGNING = "designing"          # Phase 3: design draft
    DESIGN_APPROVED = "design_approved"  # ready to advance to arch


class IdeaSessionLifecycle(SessionLifecycle):
    tool_name = "idea"
    session_prefix = "idea"
    initial_files = ("answers.md", "alternatives.md", "design.md", "events.jsonl")

    def build_meta(self, session_id: str, *, project_path: str, name: str) -> dict:
        meta = super().build_meta(session_id, project_path=project_path, name=name)
        meta["idea_status"] = IdeaStatus.GATHERING
        meta["prompt"] = ""
        return meta


# ---------------------------------------------------------------- public API


def start_idea_session(
    sessions_root: Path,
    *,
    project_path: str,
    prompt: str,
    name: str = "",
) -> dict:
    """Open a new Idea session. Returns metadata + the Phase-1 instruction.

    The AI client should now drive the `brainstorming` skill: ask one
    question per turn, record answers via `capture_idea_answer`.

    `prompt` MUST be non-empty -- the brainstorming skill needs an
    anchor idea to refine. An empty prompt would produce a session
    that has no starting point.
    """
    if not prompt or not prompt.strip():
        raise ValueError(
            "prompt must be non-empty -- the brainstorming skill needs "
            "an anchor idea to refine. Pass a one-paragraph problem "
            "statement or feature description."
        )

    lc = IdeaSessionLifecycle(sessions_root)
    sid = lc.create(project_path=project_path, name=name)
    sess_dir = lc.session_dir(sid)

    meta = json.loads((sess_dir / "meta.json").read_text(encoding="utf-8"))
    meta["prompt"] = prompt
    atomic_write_text(sess_dir / "meta.json", json.dumps(meta, indent=2))

    _append_event(sess_dir, "idea_started", {"prompt": prompt})
    return {
        "session_id": sid,
        "session_dir": str(sess_dir),
        "status": IdeaStatus.GATHERING,
        "next_skill": "brainstorming",
        "next_phase": "Phase 1: Understanding -- ask ONE question at a time, prefer multiple choice",
    }


def capture_idea_answer(
    sessions_root: Path,
    *,
    session_id: str,
    question: str,
    answer: str,
) -> dict:
    """Append a Q&A pair to the session's answers.md."""
    lc = IdeaSessionLifecycle(sessions_root)
    sess_dir = lc.session_dir(session_id)

    answers_path = sess_dir / "answers.md"
    existing = answers_path.read_text(encoding="utf-8") if answers_path.exists() else ""
    block = f"\n## Q\n{question.strip()}\n\n### A\n{answer.strip()}\n"
    atomic_write_text(answers_path, existing + block)

    _append_event(sess_dir, "idea_answer", {"q": question[:80]})
    return {"session_id": session_id, "answers_path": str(answers_path)}


def record_alternatives(
    sessions_root: Path,
    *,
    session_id: str,
    alternatives: list[dict],
    chosen_id: str = "",
) -> dict:
    """Phase 2 -- record the 2-3 design alternatives + which one was chosen.

    `alternatives` is a list of `{id, title, architecture, trade_offs}` dicts.
    """
    if not isinstance(alternatives, list) or len(alternatives) < 2:
        raise ValueError(
            "Phase 2 of brainstorming requires at least 2 alternatives "
            f"(got {len(alternatives) if isinstance(alternatives, list) else 'non-list'})"
        )

    lc = IdeaSessionLifecycle(sessions_root)
    sess_dir = lc.session_dir(session_id)

    lines = ["# Alternatives\n"]
    for alt in alternatives:
        if not isinstance(alt, dict):
            continue
        aid = alt.get("id", "")
        title = alt.get("title", "(untitled)")
        marker = " (chosen)" if aid and aid == chosen_id else ""
        lines.append(f"## {title}{marker}\n")
        if "architecture" in alt:
            lines.append(f"**Architecture:** {alt['architecture']}\n")
        if "trade_offs" in alt:
            lines.append(f"**Trade-offs:** {alt['trade_offs']}\n")
    atomic_write_text(sess_dir / "alternatives.md", "\n".join(lines) + "\n")

    _set_status(sess_dir, IdeaStatus.DESIGNING if chosen_id else IdeaStatus.EXPLORING)
    _append_event(sess_dir, "idea_alternatives", {
        "count": len(alternatives), "chosen_id": chosen_id,
    })
    return {
        "session_id": session_id,
        "alternatives_count": len(alternatives),
        "chosen_id": chosen_id,
        "status": _get_status(sess_dir),
    }


def finalize_idea_design(
    sessions_root: Path,
    *,
    session_id: str,
    design_md: str,
) -> dict:
    """Phase 3+5 -- save the consolidated design and mark the session
    ready to advance to Architecture.

    `design_md` should be the assembled Markdown the user has reviewed
    section-by-section per the brainstorming skill's Phase 3.
    """
    if not design_md or not design_md.strip():
        raise ValueError("design_md must be non-empty -- run Phase 3 first")

    lc = IdeaSessionLifecycle(sessions_root)
    sess_dir = lc.session_dir(session_id)

    atomic_write_text(sess_dir / "design.md", design_md.rstrip() + "\n")
    _set_status(sess_dir, IdeaStatus.DESIGN_APPROVED)
    _append_event(sess_dir, "idea_design_approved", {"chars": len(design_md)})
    return {
        "session_id": session_id,
        "design_path": str(sess_dir / "design.md"),
        "status": IdeaStatus.DESIGN_APPROVED,
        "ready_to_advance": True,
    }


# ---------------------------------------------------------------- helpers


def _set_status(sess_dir: Path, status: str) -> None:
    meta_path = sess_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["idea_status"] = status
    meta["updated_at"] = now_iso()
    atomic_write_text(meta_path, json.dumps(meta, indent=2))


def _get_status(sess_dir: Path) -> str:
    meta = json.loads((sess_dir / "meta.json").read_text(encoding="utf-8"))
    return meta.get("idea_status", IdeaStatus.GATHERING)


def _append_event(sess_dir: Path, event_type: str, payload: dict) -> None:
    event = {"event_type": event_type, "payload": payload, "timestamp": now_iso()}
    append_jsonl_line(sess_dir / "events.jsonl", json.dumps(event))
