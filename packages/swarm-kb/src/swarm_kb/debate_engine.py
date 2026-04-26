"""Shared debate engine -- any swarm tool can start, participate in, and resolve debates."""

import copy
import json
import logging
import os
import secrets
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

_log = logging.getLogger("swarm_kb.debate_engine")


class Verdict(str, Enum):
    SUPPORT = "support"
    OPPOSE = "oppose"
    MODIFY = "modify"


class DebateStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass
class Proposal:
    id: str = ""
    author: str = ""
    title: str = ""
    description: str = ""
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    trade_offs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "prop-" + secrets.token_hex(4)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "author": self.author,
            "title": self.title,
            "description": self.description,
            "pros": self.pros,
            "cons": self.cons,
            "trade_offs": self.trade_offs,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Proposal":
        return cls(
            id=d.get("id", ""),
            author=d.get("author", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            pros=list(d.get("pros", [])),
            cons=list(d.get("cons", [])),
            trade_offs=list(d.get("trade_offs", [])),
        )


@dataclass
class Critique:
    id: str = ""
    proposal_id: str = ""
    critic: str = ""
    verdict: Verdict = Verdict.MODIFY
    reasoning: str = ""
    suggested_changes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "crit-" + secrets.token_hex(4)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "proposal_id": self.proposal_id,
            "critic": self.critic,
            "verdict": self.verdict.value if isinstance(self.verdict, Verdict) else self.verdict,
            "reasoning": self.reasoning,
            "suggested_changes": self.suggested_changes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Critique":
        verdict_raw = d.get("verdict", "modify")
        try:
            verdict = Verdict(verdict_raw)
        except ValueError:
            verdict = Verdict.MODIFY
        return cls(
            id=d.get("id", ""),
            proposal_id=d.get("proposal_id", ""),
            critic=d.get("critic", ""),
            verdict=verdict,
            reasoning=d.get("reasoning", ""),
            suggested_changes=list(d.get("suggested_changes", [])),
        )


@dataclass
class Vote:
    agent: str = ""
    proposal_id: str = ""
    support: bool = True

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "proposal_id": self.proposal_id,
            "support": self.support,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Vote":
        return cls(
            agent=d.get("agent", ""),
            proposal_id=d.get("proposal_id", ""),
            support=d.get("support", True),
        )


@dataclass
class DebateDecision:
    title: str = ""
    chosen_proposal_id: str = ""
    rationale: str = ""
    dissenting_opinions: list[str] = field(default_factory=list)
    status: str = "accepted"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "chosen_proposal_id": self.chosen_proposal_id,
            "rationale": self.rationale,
            "dissenting_opinions": self.dissenting_opinions,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DebateDecision":
        return cls(
            title=d.get("title", ""),
            chosen_proposal_id=d.get("chosen_proposal_id", ""),
            rationale=d.get("rationale", ""),
            dissenting_opinions=list(d.get("dissenting_opinions", [])),
            status=d.get("status", "accepted"),
        )


# ---------------------------------------------------------------------------
# Debate aggregate
# ---------------------------------------------------------------------------


@dataclass
class Debate:
    """Full debate state."""

    id: str = ""
    topic: str = ""
    context: str = ""
    project_path: str = ""
    source_tool: str = ""
    source_session: str = ""
    status: DebateStatus = DebateStatus.OPEN
    proposals: list[Proposal] = field(default_factory=list)
    critiques: list[Critique] = field(default_factory=list)
    votes: list[Vote] = field(default_factory=list)
    decision: Optional[DebateDecision] = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "dbt-" + secrets.token_hex(4)
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    # -- mutations ----------------------------------------------------------

    def add_proposal(self, proposal: Proposal) -> str:
        if any(p.id == proposal.id for p in self.proposals):
            raise ValueError(f"Duplicate proposal ID: {proposal.id}")
        self.proposals.append(proposal)
        return proposal.id

    def add_critique(self, critique: Critique) -> str:
        if not any(p.id == critique.proposal_id for p in self.proposals):
            raise ValueError(
                f"Proposal {critique.proposal_id!r} does not exist in debate"
            )
        if any(c.id == critique.id for c in self.critiques):
            raise ValueError(f"Duplicate critique ID: {critique.id}")
        self.critiques.append(critique)
        return critique.id

    def add_vote(self, vote: Vote) -> None:
        if not any(p.id == vote.proposal_id for p in self.proposals):
            raise ValueError(
                f"Proposal {vote.proposal_id!r} does not exist in debate"
            )
        # Replace previous vote by same agent on same proposal
        self.votes = [
            v
            for v in self.votes
            if not (v.agent == vote.agent and v.proposal_id == vote.proposal_id)
        ]
        self.votes.append(vote)

    def tally_votes(self) -> dict[str, int]:
        """Return net support score per proposal (support +1, oppose -1)."""
        scores: dict[str, int] = {p.id: 0 for p in self.proposals}
        for v in self.votes:
            scores.setdefault(v.proposal_id, 0)
            scores[v.proposal_id] += 1 if v.support else -1
        return scores

    def get_critiques_for(self, proposal_id: str) -> list[Critique]:
        return [c for c in self.critiques if c.proposal_id == proposal_id]

    # -- resolution ---------------------------------------------------------

    def resolve(self) -> Optional[DebateDecision]:
        """Compute winning proposal based on votes. Returns decision."""
        if not self.proposals:
            return None

        scores = self.tally_votes()

        # Pick the proposal with the highest score (tie-break: first submitted)
        best_id: Optional[str] = None
        best_score = float("-inf")
        for proposal in self.proposals:
            s = scores.get(proposal.id, 0)
            if s > best_score:
                best_score = s
                best_id = proposal.id

        # Collect dissenting opinions (oppose critiques on the winner)
        dissent: list[str] = []
        if best_id is not None:
            for c in self.get_critiques_for(best_id):
                if c.verdict == Verdict.OPPOSE:
                    dissent.append(f"[{c.critic}] {c.reasoning}")

        winner = next((p for p in self.proposals if p.id == best_id), None)
        title = winner.title if winner else "No winner"

        decision = DebateDecision(
            title=title,
            chosen_proposal_id=best_id or "",
            rationale=f"Won with score {best_score} based on votes and critiques.",
            dissenting_opinions=dissent,
            status="accepted",
        )
        self.decision = decision
        self.status = DebateStatus.RESOLVED
        return decision

    # -- transcript ---------------------------------------------------------

    def get_transcript(self) -> str:
        """Generate markdown transcript."""
        lines: list[str] = []

        lines.append(f"# Debate: {self.topic}")
        if self.context:
            lines.append("")
            context_lines = self.context.split("\n")
            quoted = "\n".join(f"> {line}" for line in context_lines)
            lines.append(quoted)
        lines.append("")

        # Proposals
        if self.proposals:
            lines.append("## Proposals")
            lines.append("")
            for p in self.proposals:
                lines.append(f"### [{p.author}] {p.title}")
                lines.append("")
                lines.append(p.description)
                if p.pros:
                    lines.append("")
                    lines.append("**Pros:** " + "; ".join(p.pros))
                if p.cons:
                    lines.append("")
                    lines.append("**Cons:** " + "; ".join(p.cons))
                if p.trade_offs:
                    lines.append("")
                    lines.append("**Trade-offs:** " + "; ".join(p.trade_offs))
                lines.append("")

        # Critiques
        if self.critiques:
            lines.append("## Critiques")
            lines.append("")
            for c in self.critiques:
                lines.append(
                    f"- **{c.critic}** ({c.verdict.value}) on proposal "
                    f"`{c.proposal_id}`: {c.reasoning}"
                )
                if c.suggested_changes:
                    for ch in c.suggested_changes:
                        lines.append(f"  - {ch}")
            lines.append("")

        # Votes
        if self.votes:
            lines.append("## Votes")
            lines.append("")
            tally = self.tally_votes()
            for pid, score in sorted(tally.items(), key=lambda kv: -kv[1]):
                proposal = next((p for p in self.proposals if p.id == pid), None)
                label = proposal.title if proposal else pid
                lines.append(f"- **{label}**: score {score}")
            lines.append("")

        # Decision
        if self.decision is not None:
            lines.append("## Decision")
            lines.append("")
            d = self.decision
            status_label = d.status.upper()
            lines.append(f"**{d.title}** [{status_label}]")
            lines.append("")
            lines.append(d.rationale)
            if d.dissenting_opinions:
                lines.append("")
                lines.append("Dissenting opinions:")
                for op in d.dissenting_opinions:
                    lines.append(f"  - {op}")
            lines.append("")

        return "\n".join(lines)

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "context": self.context,
            "project_path": self.project_path,
            "source_tool": self.source_tool,
            "source_session": self.source_session,
            "status": self.status.value if isinstance(self.status, DebateStatus) else self.status,
            "proposals": [p.to_dict() for p in self.proposals],
            "critiques": [c.to_dict() for c in self.critiques],
            "votes": [v.to_dict() for v in self.votes],
            "decision": self.decision.to_dict() if self.decision else None,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Debate":
        status_raw = d.get("status", "open")
        try:
            status = DebateStatus(status_raw)
        except ValueError:
            status = DebateStatus.OPEN

        decision_raw = d.get("decision")
        decision = DebateDecision.from_dict(decision_raw) if decision_raw else None

        return cls(
            id=d.get("id", ""),
            topic=d.get("topic", ""),
            context=d.get("context", ""),
            project_path=d.get("project_path", ""),
            source_tool=d.get("source_tool", ""),
            source_session=d.get("source_session", ""),
            status=status,
            proposals=[Proposal.from_dict(p) for p in d.get("proposals", [])],
            critiques=[Critique.from_dict(c) for c in d.get("critiques", [])],
            votes=[Vote.from_dict(v) for v in d.get("votes", [])],
            decision=decision,
            created_at=d.get("created_at", ""),
        )


# ---------------------------------------------------------------------------
# Engine -- manages active debates with file-based persistence
# ---------------------------------------------------------------------------


class DebateEngine:
    """Manages active debates with file-based persistence.

    Each debate is stored in ``<debates_dir>/<debate_id>/debate.json``.
    """

    def __init__(self, debates_dir: Path) -> None:
        self._dir = Path(debates_dir)
        self._debates: dict[str, Debate] = {}
        self._lock = threading.Lock()
        self._load_all()

    # -- public API ---------------------------------------------------------

    def start_debate(
        self,
        topic: str,
        context: str = "",
        project_path: str = "",
        source_tool: str = "",
        source_session: str = "",
    ) -> Debate:
        """Start a new debate. Returns the Debate with its ID."""
        debate = Debate(
            topic=topic,
            context=context,
            project_path=project_path,
            source_tool=source_tool,
            source_session=source_session,
        )
        with self._lock:
            self._debates[debate.id] = debate
            self._save(debate.id)
        _log.info("Started debate %s: %s", debate.id, topic)
        return debate

    def get_debate(self, debate_id: str) -> Optional[Debate]:
        with self._lock:
            debate = self._get_or_load(debate_id)
            if debate is None:
                return None
            return copy.deepcopy(debate)

    def list_debates(
        self, status: str = "", source_tool: str = ""
    ) -> list[Debate]:
        with self._lock:
            self._refresh_from_disk()
            results = list(self._debates.values())
            if status:
                results = [d for d in results if d.status.value == status]
            if source_tool:
                results = [d for d in results if d.source_tool == source_tool]
            return [copy.deepcopy(d) for d in results]

    def propose(
        self,
        debate_id: str,
        author: str,
        title: str,
        description: str,
        pros: Optional[list[str]] = None,
        cons: Optional[list[str]] = None,
        trade_offs: Optional[list[str]] = None,
    ) -> str:
        """Add a proposal to an open debate. Returns proposal_id."""
        with self._lock:
            debate = self._get_or_load(debate_id)
            if debate is None:
                raise ValueError(f"Debate {debate_id!r} not found")
            if debate.status != DebateStatus.OPEN:
                raise ValueError(f"Debate {debate_id!r} is not open (status={debate.status.value})")
            proposal = Proposal(
                author=author,
                title=title,
                description=description,
                pros=pros or [],
                cons=cons or [],
                trade_offs=trade_offs or [],
            )
            proposal_id = debate.add_proposal(proposal)
            self._save(debate_id)
        _log.info("Proposal %s added to debate %s", proposal_id, debate_id)
        return proposal_id

    def critique(
        self,
        debate_id: str,
        proposal_id: str,
        critic: str,
        verdict: str,
        reasoning: str,
        suggested_changes: Optional[list[str]] = None,
    ) -> str:
        """Add a critique. Returns critique_id."""
        try:
            verdict_enum = Verdict(verdict)
        except ValueError:
            raise ValueError(f"Invalid verdict {verdict!r}. Must be one of: support, oppose, modify")
        with self._lock:
            debate = self._get_or_load(debate_id)
            if debate is None:
                raise ValueError(f"Debate {debate_id!r} not found")
            if debate.status != DebateStatus.OPEN:
                raise ValueError(f"Debate {debate_id!r} is not open (status={debate.status.value})")
            crit = Critique(
                proposal_id=proposal_id,
                critic=critic,
                verdict=verdict_enum,
                reasoning=reasoning,
                suggested_changes=suggested_changes or [],
            )
            critique_id = debate.add_critique(crit)
            self._save(debate_id)
        _log.info("Critique %s added to debate %s", critique_id, debate_id)
        return critique_id

    def vote(
        self, debate_id: str, agent: str, proposal_id: str, support: bool
    ) -> None:
        """Cast a vote."""
        with self._lock:
            debate = self._get_or_load(debate_id)
            if debate is None:
                raise ValueError(f"Debate {debate_id!r} not found")
            if debate.status != DebateStatus.OPEN:
                raise ValueError(f"Debate {debate_id!r} is not open (status={debate.status.value})")
            debate.add_vote(Vote(agent=agent, proposal_id=proposal_id, support=support))
            self._save(debate_id)
        _log.info("Vote by %s on %s in debate %s", agent, proposal_id, debate_id)

    def resolve(self, debate_id: str) -> dict:
        """Resolve debate: compute winner, generate decision, save.

        Returns ``{"decision": {...}, "transcript": "..."}``.
        """
        with self._lock:
            debate = self._get_or_load(debate_id)
            if debate is None:
                raise ValueError(f"Debate {debate_id!r} not found")
            if debate.status != DebateStatus.OPEN:
                raise ValueError(f"Debate {debate_id!r} is not open (status={debate.status.value})")
            decision = debate.resolve()
            self._save(debate_id)
            transcript = debate.get_transcript()
            self._save_transcript(debate_id, transcript)

        decision_dict = decision.to_dict() if decision else {}
        _log.info("Resolved debate %s", debate_id)
        return {"decision": decision_dict, "transcript": transcript}

    def cancel(self, debate_id: str) -> None:
        """Cancel an open debate."""
        with self._lock:
            debate = self._get_or_load(debate_id)
            if debate is None:
                raise ValueError(f"Debate {debate_id!r} not found")
            if debate.status != DebateStatus.OPEN:
                raise ValueError(f"Debate {debate_id!r} is not open (status={debate.status.value})")
            debate.status = DebateStatus.CANCELLED
            self._save(debate_id)
        _log.info("Cancelled debate %s", debate_id)

    def get_transcript(self, debate_id: str) -> str:
        """Get or generate a markdown transcript for a debate."""
        with self._lock:
            debate = self._get_or_load(debate_id)
            if debate is None:
                raise ValueError(f"Debate {debate_id!r} not found")
            return debate.get_transcript()

    # -- disk fallback ------------------------------------------------------

    def _get_or_load(self, debate_id: str) -> Optional[Debate]:
        """Return debate from memory, or try loading from disk on cache miss.

        Must be called while holding ``self._lock``.
        """
        debate = self._debates.get(debate_id)
        if debate is not None:
            return debate
        # Try loading from disk (created by another process)
        debate_file = self._dir / debate_id / "debate.json"
        if not debate_file.exists():
            return None
        try:
            data = json.loads(debate_file.read_text(encoding="utf-8"))
            debate = Debate.from_dict(data)
            self._debates[debate.id] = debate
            _log.info("Loaded debate %s from disk (created externally)", debate_id)
            return debate
        except Exception as exc:
            _log.warning("Cannot load debate %s from disk: %s", debate_id, exc)
            return None

    def _refresh_from_disk(self) -> None:
        """Scan disk for debates not yet in memory.

        Must be called while holding ``self._lock``.
        """
        if not self._dir.exists():
            return
        for entry in self._dir.iterdir():
            if not entry.is_dir():
                continue
            debate_id = entry.name
            if debate_id in self._debates:
                continue
            debate_file = entry / "debate.json"
            if not debate_file.exists():
                continue
            try:
                data = json.loads(debate_file.read_text(encoding="utf-8"))
                debate = Debate.from_dict(data)
                self._debates[debate.id] = debate
                _log.info("Discovered debate %s from disk", debate_id)
            except Exception as exc:
                _log.warning("Skipping corrupt debate in %s: %s", entry, exc)

    # -- persistence --------------------------------------------------------

    def _save(self, debate_id: str) -> None:
        """Save debate state to ``<dir>/<debate_id>/debate.json``.

        Must be called while holding ``self._lock``.
        Uses atomic write via tempfile + os.replace.
        """
        debate = self._debates.get(debate_id)
        if debate is None:
            return
        debate_dir = self._dir / debate_id
        debate_dir.mkdir(parents=True, exist_ok=True)
        path = debate_dir / "debate.json"
        content = json.dumps(debate.to_dict(), indent=2) + "\n"
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(debate_dir), suffix=".tmp")
        try:
            fh = os.fdopen(tmp_fd, "w", encoding="utf-8")
            with fh:
                fh.write(content)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _save_transcript(self, debate_id: str, transcript: str) -> None:
        """Save the markdown transcript alongside the debate JSON.

        Uses atomic write via tempfile + os.replace.
        """
        debate_dir = self._dir / debate_id
        debate_dir.mkdir(parents=True, exist_ok=True)
        path = debate_dir / "transcript.md"
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(debate_dir), suffix=".tmp")
        try:
            fh = os.fdopen(tmp_fd, "w", encoding="utf-8")
            with fh:
                fh.write(transcript)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load_all(self) -> None:
        """Load all debate directories on startup."""
        if not self._dir.exists():
            return
        with self._lock:
            for entry in sorted(self._dir.iterdir()):
                if not entry.is_dir():
                    continue
                debate_file = entry / "debate.json"
                if not debate_file.exists():
                    continue
                try:
                    data = json.loads(debate_file.read_text(encoding="utf-8"))
                    debate = Debate.from_dict(data)
                    self._debates[debate.id] = debate
                except Exception as exc:
                    _log.warning("Skipping corrupt debate in %s: %s", entry, exc)

    def count(self, status: str = "") -> int:
        """Count debates, optionally filtered by status."""
        with self._lock:
            self._refresh_from_disk()
            if not status:
                return len(self._debates)
            return sum(
                1 for d in self._debates.values() if d.status.value == status
            )
