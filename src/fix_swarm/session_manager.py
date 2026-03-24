"""FixSessionManager -- manages multi-agent fix sessions with proposals, claims, and messaging."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import (
    ClaimStatus,
    Event,
    EventType,
    FindingClaim,
    FixProposal,
    Message,
    MessageType,
    ProposalStatus,
    Reaction,
    ReactionType,
)


def _default_sessions_dir() -> Path:
    return Path.home() / ".swarm-kb" / "fix" / "sessions"


class FixSessionManager:
    """Manages multi-agent fix sessions with proposals, claims, and messaging."""

    def __init__(self, sessions_dir: Optional[Path] = None):
        self._dir = sessions_dir or _default_sessions_dir()
        self._sessions: dict[str, dict] = {}  # session_id -> metadata
        self._proposals: dict[str, list[FixProposal]] = {}
        self._claims: dict[str, list[FindingClaim]] = {}
        self._messages: dict[str, list[Message]] = {}
        self._events: dict[str, list[Event]] = {}
        self._findings: dict[str, list[dict]] = {}
        self._phase_done: dict[str, dict[str, set]] = {}
        self._lock = threading.Lock()

        # Load any existing sessions from disk on startup
        self._discover_existing_sessions()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start_session(
        self,
        review_session: str = "",
        project_path: str = "",
        name: str = "",
    ) -> str:
        """Create a new fix session. Returns session_id."""
        with self._lock:
            session_id = self._generate_session_id()
            now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            self._sessions[session_id] = {
                "session_id": session_id,
                "name": name or session_id,
                "review_session": review_session,
                "project_path": project_path,
                "status": "active",
                "created": now,
                "ended": "",
                "phases_done": {},  # expert_role -> set of phase ints (stored as list)
            }
            self._proposals[session_id] = []
            self._claims[session_id] = []
            self._messages[session_id] = []
            self._events[session_id] = []
            self._findings[session_id] = []
            self._phase_done[session_id] = {}
            self._save_session(session_id)
            return session_id

    def end_session(self, session_id: str) -> dict:
        """End session, generate summary, persist to disk."""
        with self._lock:
            meta = self._require_session(session_id)
            meta["status"] = "ended"
            meta["ended"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"

            # Post a SESSION_ENDED event
            ev = Event(event_type=EventType.SESSION_ENDED, payload={"session_id": session_id})
            self._events[session_id].append(ev)

            self._save_session(session_id)
            return self._build_summary(session_id)

    def get_session(self, session_id: str) -> dict:
        """Get session metadata + stats."""
        with self._lock:
            meta = dict(self._require_session(session_id))
            proposals = self._proposals.get(session_id, [])
            meta["stats"] = {
                "total_proposals": len(proposals),
                "proposed": sum(1 for p in proposals if p.status == ProposalStatus.PROPOSED),
                "approved": sum(1 for p in proposals if p.status == ProposalStatus.APPROVED),
                "rejected": sum(1 for p in proposals if p.status == ProposalStatus.REJECTED),
                "applied": sum(1 for p in proposals if p.status == ProposalStatus.APPLIED),
                "failed": sum(1 for p in proposals if p.status == ProposalStatus.FAILED),
                "active_claims": sum(
                    1 for c in self._claims.get(session_id, []) if c.status == ClaimStatus.ACTIVE
                ),
                "total_messages": len(self._messages.get(session_id, [])),
                "total_events": len(self._events.get(session_id, [])),
            }
            return meta

    def list_sessions(self) -> list[dict]:
        """List all fix sessions (metadata only, no full stats)."""
        with self._lock:
            return [dict(m) for m in self._sessions.values()]

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------

    def claim_finding(self, session_id: str, finding_id: str, expert_role: str) -> dict:
        """Claim a finding for an expert. Prevents double-claims."""
        with self._lock:
            self._require_session(session_id)
            claims = self._claims[session_id]

            # Check if already actively claimed
            for c in claims:
                if c.finding_id == finding_id and c.status == ClaimStatus.ACTIVE:
                    if c.expert_role == expert_role:
                        return {"ok": True, "already_claimed": True, "claim": c.to_dict()}
                    return {
                        "ok": False,
                        "error": f"Finding {finding_id} already claimed by {c.expert_role}",
                    }

            claim = FindingClaim(
                finding_id=finding_id,
                expert_role=expert_role,
                status=ClaimStatus.ACTIVE,
            )
            claims.append(claim)

            ev = Event(
                event_type=EventType.FINDING_CLAIMED,
                payload={"finding_id": finding_id, "expert_role": expert_role},
            )
            self._events[session_id].append(ev)
            self._save_session(session_id)
            return {"ok": True, "already_claimed": False, "claim": claim.to_dict()}

    def release_finding(self, session_id: str, finding_id: str, expert_role: str) -> dict:
        """Release a claim on a finding."""
        with self._lock:
            self._require_session(session_id)
            claims = self._claims[session_id]

            for c in claims:
                if (
                    c.finding_id == finding_id
                    and c.expert_role == expert_role
                    and c.status == ClaimStatus.ACTIVE
                ):
                    c.status = ClaimStatus.RELEASED
                    ev = Event(
                        event_type=EventType.FINDING_RELEASED,
                        payload={"finding_id": finding_id, "expert_role": expert_role},
                    )
                    self._events[session_id].append(ev)
                    self._save_session(session_id)
                    return {"ok": True, "claim": c.to_dict()}

            return {"ok": False, "error": f"No active claim found for {finding_id} by {expert_role}"}

    def get_claims(self, session_id: str) -> list[dict]:
        """Get all claims for a session."""
        with self._lock:
            self._require_session(session_id)
            return [c.to_dict() for c in self._claims[session_id]]

    # ------------------------------------------------------------------
    # Proposals
    # ------------------------------------------------------------------

    def propose_fix(self, session_id: str, proposal: FixProposal) -> str:
        """Post a fix proposal. Returns proposal_id."""
        with self._lock:
            self._require_session(session_id)
            # Ensure the proposal has an id
            if not proposal.id:
                proposal.__post_init__()
            self._proposals[session_id].append(proposal)

            ev = Event(
                event_type=EventType.FIX_PROPOSED,
                payload={"proposal_id": proposal.id, "expert_role": proposal.expert_role,
                         "finding_id": proposal.finding_id, "file": proposal.file},
            )
            self._events[session_id].append(ev)
            self._save_session(session_id)
            return proposal.id

    def get_proposals(
        self,
        session_id: str,
        status: str = "",
        expert_role: str = "",
        file: str = "",
    ) -> list[dict]:
        """Get proposals with optional filters."""
        with self._lock:
            self._require_session(session_id)
            results = self._proposals[session_id]
            if status:
                results = [p for p in results if p.status.value == status]
            if expert_role:
                results = [p for p in results if p.expert_role == expert_role]
            if file:
                results = [p for p in results if p.file == file]
            return [p.to_dict() for p in results]

    def update_proposal_status(
        self, session_id: str, proposal_id: str, status: ProposalStatus
    ) -> dict:
        """Update the status of a proposal."""
        with self._lock:
            self._require_session(session_id)
            proposal = self._find_proposal(session_id, proposal_id)
            if proposal is None:
                return {"ok": False, "error": f"Proposal {proposal_id} not found"}

            old_status = proposal.status
            proposal.status = status

            event_map = {
                ProposalStatus.APPROVED: EventType.FIX_APPROVED,
                ProposalStatus.REJECTED: EventType.FIX_REJECTED,
                ProposalStatus.APPLIED: EventType.FIX_APPLIED,
                ProposalStatus.FAILED: EventType.FIX_FAILED,
                ProposalStatus.VERIFIED: EventType.FIX_VERIFIED,
            }
            evt_type = event_map.get(status, EventType.FIX_PROPOSED)
            ev = Event(
                event_type=evt_type,
                payload={
                    "proposal_id": proposal_id,
                    "old_status": old_status.value,
                    "new_status": status.value,
                },
            )
            self._events[session_id].append(ev)
            self._save_session(session_id)
            return {"ok": True, "proposal": proposal.to_dict()}

    # ------------------------------------------------------------------
    # Reactions
    # ------------------------------------------------------------------

    def add_reaction(self, session_id: str, proposal_id: str, reaction: Reaction) -> dict:
        """React to a proposal. Auto-updates status if consensus reached."""
        with self._lock:
            self._require_session(session_id)
            proposal = self._find_proposal(session_id, proposal_id)
            if proposal is None:
                return {"ok": False, "error": f"Proposal {proposal_id} not found"}

            # Prevent duplicate reactions from the same expert
            for existing in proposal.reactions:
                if existing.expert == reaction.expert:
                    return {
                        "ok": False,
                        "error": f"Expert {reaction.expert} already reacted to {proposal_id}",
                    }

            proposal.reactions.append(reaction)

            ev = Event(
                event_type=EventType.REACTION_ADDED,
                payload={
                    "proposal_id": proposal_id,
                    "expert": reaction.expert,
                    "reaction_type": reaction.reaction_type.value,
                },
            )
            self._events[session_id].append(ev)

            # Auto-consensus check (inline, already holding lock)
            consensus = self._check_consensus_unlocked(session_id, proposal_id, threshold=2)

            self._save_session(session_id)
            return {"ok": True, "proposal": proposal.to_dict(), "consensus": consensus}

    def check_consensus(self, session_id: str, proposal_id: str, threshold: int = 2) -> dict:
        """Check if a proposal has reached consensus."""
        with self._lock:
            self._require_session(session_id)
            return self._check_consensus_unlocked(session_id, proposal_id, threshold)

    def _check_consensus_unlocked(
        self, session_id: str, proposal_id: str, threshold: int = 2
    ) -> dict:
        """Internal consensus check (caller must hold lock)."""
        proposal = self._find_proposal(session_id, proposal_id)
        if proposal is None:
            return {"reached": False, "reason": "proposal_not_found"}

        # If already in a terminal status, just report it
        if proposal.status in (
            ProposalStatus.APPLIED,
            ProposalStatus.FAILED,
        ):
            return {"reached": True, "status": proposal.status.value, "reason": "terminal_status"}

        approvals = sum(
            1 for r in proposal.reactions if r.reaction_type == ReactionType.APPROVE
        )
        rejections = sum(
            1 for r in proposal.reactions if r.reaction_type == ReactionType.REJECT
        )

        # Any rejection causes REJECTED (can be overridden via update_proposal_status)
        if rejections > 0 and proposal.status == ProposalStatus.PROPOSED:
            proposal.status = ProposalStatus.REJECTED
            ev = Event(
                event_type=EventType.FIX_REJECTED,
                payload={"proposal_id": proposal_id, "rejections": rejections},
            )
            self._events[session_id].append(ev)
            return {
                "reached": True,
                "status": ProposalStatus.REJECTED.value,
                "reason": "rejected",
                "rejections": rejections,
                "approvals": approvals,
            }

        # Enough approvals => APPROVED
        if approvals >= threshold and proposal.status == ProposalStatus.PROPOSED:
            proposal.status = ProposalStatus.APPROVED
            ev = Event(
                event_type=EventType.FIX_APPROVED,
                payload={"proposal_id": proposal_id, "approvals": approvals},
            )
            self._events[session_id].append(ev)
            return {
                "reached": True,
                "status": ProposalStatus.APPROVED.value,
                "reason": "threshold_met",
                "approvals": approvals,
                "rejections": rejections,
            }

        return {
            "reached": False,
            "status": proposal.status.value,
            "approvals": approvals,
            "rejections": rejections,
            "threshold": threshold,
        }

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def send_message(self, session_id: str, message: Message) -> str:
        """Send a message in a session. Returns message id."""
        with self._lock:
            self._require_session(session_id)
            if not message.id:
                message.__post_init__()
            self._messages[session_id].append(message)

            ev = Event(
                event_type=EventType.MESSAGE,
                payload={
                    "message_id": message.id,
                    "sender": message.sender,
                    "recipient": message.recipient,
                    "msg_type": message.msg_type.value,
                },
            )
            self._events[session_id].append(ev)
            self._save_session(session_id)
            return message.id

    def get_inbox(self, session_id: str, expert_role: str) -> list[dict]:
        """Get messages addressed to an expert (direct + broadcasts)."""
        with self._lock:
            self._require_session(session_id)
            results: list[dict] = []
            for msg in self._messages[session_id]:
                if msg.recipient == expert_role or msg.recipient == "all":
                    results.append(msg.to_dict())
                # Also include responses to queries the expert sent
                elif msg.msg_type == MessageType.RESPONSE and msg.recipient == expert_role:
                    results.append(msg.to_dict())
            return results

    def broadcast(self, session_id: str, sender: str, content: str) -> str:
        """Send a broadcast message to all experts. Returns message id."""
        msg = Message(
            sender=sender,
            recipient="all",
            msg_type=MessageType.BROADCAST,
            content=content,
        )
        return self.send_message(session_id, msg)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def post_event(self, session_id: str, event: Event) -> None:
        """Post a custom event."""
        with self._lock:
            self._require_session(session_id)
            if not event.id:
                event.__post_init__()
            self._events[session_id].append(event)
            self._save_session(session_id)

    def get_events(self, session_id: str, after: int = 0) -> list[dict]:
        """Get events, optionally starting after a given index."""
        with self._lock:
            self._require_session(session_id)
            events = self._events[session_id]
            return [e.to_dict() for e in events[after:]]

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------

    def mark_phase_done(self, session_id: str, expert_role: str, phase: int) -> dict:
        """Mark that an expert has completed a phase."""
        with self._lock:
            meta = self._require_session(session_id)
            phases_done = meta.setdefault("phases_done", {})
            expert_phases = phases_done.setdefault(expert_role, [])
            if phase not in expert_phases:
                expert_phases.append(phase)
            self._save_session(session_id)
            return {
                "ok": True,
                "expert_role": expert_role,
                "phase": phase,
                "phases_done": dict(phases_done),
            }

    def check_phase_ready(self, session_id: str, phase: int) -> dict:
        """Check if all participating experts have completed a phase."""
        with self._lock:
            meta = self._require_session(session_id)
            phases_done = meta.get("phases_done", {})
            claims = self._claims.get(session_id, [])

            # Participating experts = those with active claims
            active_experts = {c.expert_role for c in claims if c.status == ClaimStatus.ACTIVE}
            if not active_experts:
                return {"ready": True, "phase": phase, "waiting_on": [], "active_experts": []}

            done_experts = {
                role for role, done_list in phases_done.items() if phase in done_list
            }
            waiting = sorted(active_experts - done_experts)
            return {
                "ready": len(waiting) == 0,
                "phase": phase,
                "waiting_on": waiting,
                "done": sorted(done_experts & active_experts),
                "active_experts": sorted(active_experts),
            }

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    def add_finding(self, session_id: str, finding: dict) -> None:
        """Store a finding from review/arch in the session."""
        with self._lock:
            self._require_session(session_id)
            if session_id not in self._findings:
                self._findings[session_id] = []
            self._findings[session_id].append(finding)
            self._save_session(session_id)

    def get_findings(self, session_id: str) -> list[dict]:
        """Get all findings for a session."""
        with self._lock:
            return list(self._findings.get(session_id, []))

    # ------------------------------------------------------------------
    # Proposal aliases (API compatibility with server.py)
    # ------------------------------------------------------------------

    def add_proposal(self, session_id: str, proposal: FixProposal) -> str:
        """Add a proposal. Alias for propose_fix for API compat."""
        return self.propose_fix(session_id, proposal)

    def get_proposal_by_id(self, session_id: str, proposal_id: str) -> Optional[dict]:
        """Get a single proposal by ID."""
        with self._lock:
            for p in self._proposals.get(session_id, []):
                if p.id == proposal_id:
                    return p.to_dict()
            return None

    # ------------------------------------------------------------------
    # Message aliases (API compatibility with server.py)
    # ------------------------------------------------------------------

    def add_message(self, session_id: str, message: Message) -> str:
        """Store a message."""
        return self.send_message(session_id, message)

    def get_messages(self, session_id: str, recipient: str = "") -> list[dict]:
        """Get messages, optionally filtered by recipient."""
        with self._lock:
            self._require_session(session_id)
            msgs = self._messages.get(session_id, [])
            if recipient:
                msgs = [m for m in msgs if m.recipient in (recipient, "all")]
            return [m.to_dict() for m in msgs]

    def mark_message_read(self, session_id: str, message_id: str) -> None:
        """Mark a message as read (no-op for now, messages don't track read state)."""
        pass

    # ------------------------------------------------------------------
    # Phase data (API compatibility with server.py)
    # ------------------------------------------------------------------

    def get_phase_data(self, session_id: str) -> dict:
        """Get phase completion data.

        Returns a dict keyed by expert_role -> sorted list of completed phases.
        """
        with self._lock:
            meta = self._require_session(session_id)
            phases = meta.get("phases_done", {})
            return {expert: sorted(list(ps)) for expert, ps in phases.items()}

    @property
    def sessions_dir(self) -> Path:
        """Base directory for sessions."""
        return self._dir

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self, session_id: str) -> dict:
        """Generate summary: proposals by status, reactions, applied fixes."""
        with self._lock:
            self._require_session(session_id)
            return self._build_summary(session_id)

    def _build_summary(self, session_id: str) -> dict:
        """Internal summary builder (caller must hold lock)."""
        meta = self._sessions[session_id]
        proposals = self._proposals.get(session_id, [])
        claims = self._claims.get(session_id, [])
        messages = self._messages.get(session_id, [])
        events = self._events.get(session_id, [])

        status_counts: dict[str, int] = {}
        for p in proposals:
            status_counts[p.status.value] = status_counts.get(p.status.value, 0) + 1

        total_reactions = sum(len(p.reactions) for p in proposals)

        applied_fixes = [p.to_dict() for p in proposals if p.status == ProposalStatus.APPLIED]
        rejected_fixes = [p.to_dict() for p in proposals if p.status == ProposalStatus.REJECTED]

        experts_involved = sorted(
            {p.expert_role for p in proposals}
            | {c.expert_role for c in claims}
            | {m.sender for m in messages if m.sender}
        )

        files_touched = sorted({p.file for p in proposals if p.file})

        return {
            "session_id": session_id,
            "name": meta.get("name", ""),
            "status": meta.get("status", ""),
            "created": meta.get("created", ""),
            "ended": meta.get("ended", ""),
            "review_session": meta.get("review_session", ""),
            "project_path": meta.get("project_path", ""),
            "proposal_counts": status_counts,
            "total_proposals": len(proposals),
            "total_reactions": total_reactions,
            "total_messages": len(messages),
            "total_events": len(events),
            "applied_fixes": applied_fixes,
            "rejected_fixes": rejected_fixes,
            "experts_involved": experts_involved,
            "files_touched": files_touched,
            "active_claims": sum(1 for c in claims if c.status == ClaimStatus.ACTIVE),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _session_dir(self, session_id: str) -> Path:
        return self._dir / session_id

    def _save_session(self, session_id: str) -> None:
        """Persist session state to disk (proposals.jsonl, messages.jsonl, events.jsonl, meta.json).

        Caller must hold ``self._lock``.
        """
        sdir = self._session_dir(session_id)
        sdir.mkdir(parents=True, exist_ok=True)

        # meta.json
        meta = dict(self._sessions[session_id])
        # Ensure phases_done is serialisable (sets -> lists)
        pd = meta.get("phases_done", {})
        meta["phases_done"] = {k: list(v) for k, v in pd.items()}
        (sdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        # proposals.jsonl
        with open(sdir / "proposals.jsonl", "w", encoding="utf-8") as f:
            for p in self._proposals.get(session_id, []):
                f.write(json.dumps(p.to_dict()) + "\n")

        # claims.jsonl
        with open(sdir / "claims.jsonl", "w", encoding="utf-8") as f:
            for c in self._claims.get(session_id, []):
                f.write(json.dumps(c.to_dict()) + "\n")

        # messages.jsonl
        with open(sdir / "messages.jsonl", "w", encoding="utf-8") as f:
            for m in self._messages.get(session_id, []):
                f.write(json.dumps(m.to_dict()) + "\n")

        # events.jsonl
        with open(sdir / "events.jsonl", "w", encoding="utf-8") as f:
            for e in self._events.get(session_id, []):
                f.write(json.dumps(e.to_dict()) + "\n")

        # findings.jsonl
        with open(sdir / "findings.jsonl", "w", encoding="utf-8") as f:
            for finding in self._findings.get(session_id, []):
                f.write(json.dumps(finding) + "\n")

    def _load_session(self, session_id: str) -> None:
        """Load session state from disk. Caller must hold ``self._lock``."""
        sdir = self._session_dir(session_id)
        if not sdir.exists():
            return

        # meta.json
        meta_path = sdir / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self._sessions[session_id] = meta
        else:
            return  # no meta => skip

        # proposals.jsonl
        self._proposals[session_id] = []
        proposals_path = sdir / "proposals.jsonl"
        if proposals_path.exists():
            for line in proposals_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    self._proposals[session_id].append(FixProposal.from_dict(json.loads(line)))

        # claims.jsonl
        self._claims[session_id] = []
        claims_path = sdir / "claims.jsonl"
        if claims_path.exists():
            for line in claims_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    self._claims[session_id].append(FindingClaim.from_dict(json.loads(line)))

        # messages.jsonl
        self._messages[session_id] = []
        messages_path = sdir / "messages.jsonl"
        if messages_path.exists():
            for line in messages_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    self._messages[session_id].append(Message.from_dict(json.loads(line)))

        # events.jsonl
        self._events[session_id] = []
        events_path = sdir / "events.jsonl"
        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    self._events[session_id].append(Event.from_dict(json.loads(line)))

        # findings.jsonl
        self._findings[session_id] = []
        findings_path = sdir / "findings.jsonl"
        if findings_path.exists():
            for line in findings_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    self._findings[session_id].append(json.loads(line))

        # Rebuild _phase_done from meta
        self._phase_done[session_id] = {}
        for expert, phases in meta.get("phases_done", {}).items():
            self._phase_done[session_id][expert] = set(phases)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_session(self, session_id: str) -> dict:
        """Return session metadata or raise KeyError."""
        if session_id not in self._sessions:
            raise KeyError(f"Session {session_id!r} not found")
        return self._sessions[session_id]

    def _find_proposal(self, session_id: str, proposal_id: str) -> Optional[FixProposal]:
        """Find a proposal by id within a session (caller must hold lock)."""
        for p in self._proposals.get(session_id, []):
            if p.id == proposal_id:
                return p
        return None

    def _generate_session_id(self) -> str:
        """Generate a session ID like fix-2026-03-23-001."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        prefix = f"fix-{today}-"

        # Find the next available number
        existing = [
            sid for sid in self._sessions if sid.startswith(prefix)
        ]
        # Also check on-disk directories
        if self._dir.exists():
            for d in self._dir.iterdir():
                if d.is_dir() and d.name.startswith(prefix) and d.name not in existing:
                    existing.append(d.name)

        max_n = 0
        for sid in existing:
            suffix = sid[len(prefix):]
            try:
                n = int(suffix)
                if n > max_n:
                    max_n = n
            except ValueError:
                pass
        return f"{prefix}{max_n + 1:03d}"

    def _discover_existing_sessions(self) -> None:
        """Scan the sessions directory and load any existing sessions."""
        if not self._dir.exists():
            return
        for d in sorted(self._dir.iterdir()):
            if d.is_dir() and (d / "meta.json").exists():
                sid = d.name
                if sid not in self._sessions:
                    self._load_session(sid)
