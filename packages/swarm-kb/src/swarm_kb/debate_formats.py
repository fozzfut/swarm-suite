"""Debate format registry -- 13 named protocols over the same DebateEngine.

A "format" tells participating agents which roles exist, which phases
the debate moves through, and what a clean stop looks like. The
underlying state model (proposals/critiques/votes/resolve) is unchanged
-- agents just follow a different *protocol* on top of it.

Formats currently supported (full swarms-library mapping plus `open`):

  * `open` -- legacy free-form propose/critique/vote/resolve. Default.
  * `with_judge` -- pro/con sides + neutral judge; judge synthesis seeds
    the next round. Iterative refinement.
  * `trial` -- prosecution/defense/judge with structured phases.
  * `mediation` -- mediator-facilitated resolution between two parties.
  * `one_on_one` -- two agents alternate, no judge.
  * `expert_panel` -- N domain experts + a moderator who synthesises.
  * `round_table` -- egalitarian, every participant proposes/critiques/votes.
  * `interview` -- one interviewer, one or more respondents; non-adversarial.
  * `peer_review` -- author + N reviewers + editor (academic-style).
  * `brainstorming` -- diverge then converge; no critiques during diverge.
  * `council` -- formal stakeholder body with chair tie-break authority.
  * `mentorship` -- mentor coaches mentee through a decision.
  * `negotiation` -- two parties bargain toward shared terms over rounds.

The format spec is text, not code -- agents read the spec to know what
to do. This is intentional: the AI client is the one running the loop,
and we want the protocol to be inspectable, version-able, and editable
without restarting the server.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class DebatePhase:
    """One phase in a debate format protocol."""

    name: str
    actors: list[str]
    description: str
    expected_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "actors": list(self.actors),
            "description": self.description,
            "expected_actions": list(self.expected_actions),
        }


@dataclass
class DebateFormat:
    """A named multi-agent debate protocol."""

    name: str
    summary: str
    actors: list[str]
    phases: list[DebatePhase]
    stop_condition: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "summary": self.summary,
            "actors": list(self.actors),
            "phases": [p.to_dict() for p in self.phases],
            "stop_condition": self.stop_condition,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Built-in formats
# ---------------------------------------------------------------------------


_OPEN = DebateFormat(
    name="open",
    summary="Free-form propose/critique/vote/resolve. The legacy default.",
    actors=["proposer", "critic", "voter"],
    phases=[
        DebatePhase(
            name="propose",
            actors=["proposer"],
            description="Each participating agent submits a proposal with pros/cons.",
            expected_actions=["kb_propose"],
        ),
        DebatePhase(
            name="critique",
            actors=["critic"],
            description="Critics post a verdict (support/oppose/modify) with reasoning per proposal.",
            expected_actions=["kb_critique"],
        ),
        DebatePhase(
            name="vote",
            actors=["voter"],
            description="Voters cast support/oppose per proposal.",
            expected_actions=["kb_vote"],
        ),
        DebatePhase(
            name="resolve",
            actors=["facilitator"],
            description="Tally votes, pick winner, write decision and dissenting opinions.",
            expected_actions=["kb_resolve_debate"],
        ),
    ],
    stop_condition="resolve has been called",
)


_WITH_JUDGE = DebateFormat(
    name="with_judge",
    summary=(
        "Pro/Con sides + neutral judge. Each round: pro and con submit "
        "proposals, judge synthesises a verdict; that synthesis seeds "
        "the next round until the judge rules a final winner. Iterative "
        "refinement, not a single shot."
    ),
    actors=["pro", "con", "judge"],
    phases=[
        DebatePhase(
            name="open_round",
            actors=["pro", "con"],
            description=(
                "Pro submits a proposal arguing the affirmative; "
                "Con submits one arguing the negative. Each round must "
                "produce exactly one proposal per side."
            ),
            expected_actions=["kb_propose (pro)", "kb_propose (con)"],
        ),
        DebatePhase(
            name="judge_synthesis",
            actors=["judge"],
            description=(
                "Judge writes a critique on each proposal explaining "
                "what stands and what doesn't. The synthesis becomes "
                "the BACKGROUND for the next round (publishers should "
                "carry it as `background.previous_synthesis`)."
            ),
            expected_actions=["kb_critique (judge, verdict=modify)"],
        ),
        DebatePhase(
            name="next_round_or_resolve",
            actors=["judge"],
            description=(
                "Judge decides: continue with another round (start a "
                "new open_round phase carrying the synthesis as "
                "background) OR resolve. Cap at 5 rounds by convention."
            ),
            expected_actions=["kb_propose / kb_resolve_debate"],
        ),
    ],
    stop_condition="judge calls resolve_debate or 5 rounds complete",
    notes=(
        "Each round's judge critique seeds the next round's background. "
        "Use Message.background={'previous_synthesis': ...} when "
        "publishing on the bus."
    ),
)


_TRIAL = DebateFormat(
    name="trial",
    summary=(
        "Prosecution / defense / judge with structured phases. Fits "
        "security findings, regression-class bugs, breaking-change "
        "proposals -- anywhere one side wants action and the other "
        "wants the status quo, with a third party deciding."
    ),
    actors=["prosecution", "defense", "judge"],
    phases=[
        DebatePhase(
            name="charge",
            actors=["prosecution"],
            description=(
                "Prosecution submits ONE proposal: the charge. It "
                "names the alleged defect, severity, and the requested "
                "remedy."
            ),
            expected_actions=["kb_propose (prosecution)"],
        ),
        DebatePhase(
            name="defense",
            actors=["defense"],
            description=(
                "Defense critiques the charge with verdict=oppose or "
                "verdict=modify; reasoning must address the prosecution's "
                "evidence point-by-point."
            ),
            expected_actions=["kb_critique (defense)"],
        ),
        DebatePhase(
            name="rebuttal",
            actors=["prosecution"],
            description=(
                "Prosecution may respond to the defense critique by "
                "submitting an amended proposal or further critiques. "
                "Optional but expected for high-severity charges."
            ),
            expected_actions=["kb_propose (amended) / kb_critique"],
        ),
        DebatePhase(
            name="ruling",
            actors=["judge"],
            description=(
                "Judge resolves the debate by writing the decision. "
                "Decision rationale must cite which evidence carried "
                "and which was dismissed."
            ),
            expected_actions=["kb_resolve_debate"],
        ),
    ],
    stop_condition="judge calls resolve_debate",
    notes=(
        "Map onto a finding by setting Debate.context to the finding ID. "
        "Severity escalation is the prosecution's burden; the judge "
        "MUST NOT escalate beyond what the charge requested."
    ),
)


_MEDIATION = DebateFormat(
    name="mediation",
    summary=(
        "Mediator-facilitated resolution between two parties with "
        "conflicting findings on the same line/file. No vote; the "
        "mediator synthesises common ground and writes a unified "
        "decision both parties can accept."
    ),
    actors=["party_a", "party_b", "mediator"],
    phases=[
        DebatePhase(
            name="positions",
            actors=["party_a", "party_b"],
            description=(
                "Each party submits exactly one proposal stating its "
                "position and the minimum it needs to accept the other "
                "side's view. Mediator does not propose."
            ),
            expected_actions=["kb_propose (party_a)", "kb_propose (party_b)"],
        ),
        DebatePhase(
            name="cross_critique",
            actors=["party_a", "party_b"],
            description=(
                "Each party critiques the OTHER side's proposal. "
                "Verdicts must be modify (not oppose) -- mediation "
                "assumes both parties are negotiating in good faith."
            ),
            expected_actions=["kb_critique"],
        ),
        DebatePhase(
            name="mediation",
            actors=["mediator"],
            description=(
                "Mediator submits a unified proposal that incorporates "
                "the must-haves from both parties. Mediator then resolves "
                "the debate selecting their own proposal."
            ),
            expected_actions=["kb_propose (mediator)", "kb_resolve_debate"],
        ),
    ],
    stop_condition="mediator calls resolve_debate",
    notes=(
        "Used when two reviewer experts post contradictory findings on "
        "the same file:line. The mediator role MAY be a generalist "
        "expert (e.g. project-architect) rather than a domain specialist."
    ),
)


_ONE_ON_ONE = DebateFormat(
    name="one_on_one",
    summary=(
        "Two agents alternate proposals on a single question. No judge, "
        "no panel; the second proposal wins by convention if neither side "
        "concedes via critique. Lightest-weight format -- use when only "
        "two viewpoints are at stake."
    ),
    actors=["agent_a", "agent_b"],
    phases=[
        DebatePhase(
            name="opening",
            actors=["agent_a", "agent_b"],
            description="Each side submits one proposal stating its position.",
            expected_actions=["kb_propose"],
        ),
        DebatePhase(
            name="rebuttal",
            actors=["agent_a", "agent_b"],
            description="Each side critiques the other; verdict=oppose|modify.",
            expected_actions=["kb_critique"],
        ),
        DebatePhase(
            name="resolve",
            actors=["facilitator"],
            description="Tally votes (each side votes once) -- ties go to agent_b by convention.",
            expected_actions=["kb_vote", "kb_resolve_debate"],
        ),
    ],
    stop_condition="resolve called",
)


_EXPERT_PANEL = DebateFormat(
    name="expert_panel",
    summary=(
        "N domain experts each contribute a proposal from their angle. "
        "A moderator synthesises the tradeoffs into a unified decision. "
        "Use when a question touches multiple domains and you want each "
        "covered explicitly."
    ),
    actors=["panelist", "moderator"],
    phases=[
        DebatePhase(
            name="contributions",
            actors=["panelist"],
            description="Each panelist submits ONE proposal from their domain perspective.",
            expected_actions=["kb_propose"],
        ),
        DebatePhase(
            name="cross_critique",
            actors=["panelist"],
            description="Panelists critique each other's proposals (verdict=modify expected).",
            expected_actions=["kb_critique"],
        ),
        DebatePhase(
            name="synthesis",
            actors=["moderator"],
            description="Moderator submits a unified proposal that names the tradeoffs and resolves.",
            expected_actions=["kb_propose", "kb_resolve_debate"],
        ),
    ],
    stop_condition="moderator calls resolve_debate",
    notes="Set Debate.context to the cross-domain question; one panelist per relevant expert YAML.",
)


_ROUND_TABLE = DebateFormat(
    name="round_table",
    summary=(
        "Egalitarian: every participant proposes, every participant "
        "critiques every other proposal, every participant votes. No "
        "moderator role; the highest-vote proposal wins. Use when the "
        "group is small (<=5) and you want full coverage."
    ),
    actors=["participant"],
    phases=[
        DebatePhase(
            name="propose",
            actors=["participant"],
            description="Each participant submits exactly one proposal.",
            expected_actions=["kb_propose"],
        ),
        DebatePhase(
            name="critique_all",
            actors=["participant"],
            description="Each participant critiques every other proposal at least once.",
            expected_actions=["kb_critique"],
        ),
        DebatePhase(
            name="vote",
            actors=["participant"],
            description="Each participant votes once per proposal (incl. their own).",
            expected_actions=["kb_vote"],
        ),
        DebatePhase(
            name="resolve",
            actors=["facilitator"],
            description="Tally and resolve; ties broken by submission order.",
            expected_actions=["kb_resolve_debate"],
        ),
    ],
    stop_condition="resolve called",
)


_INTERVIEW = DebateFormat(
    name="interview",
    summary=(
        "One interviewer asks a sequence of questions; one or more "
        "respondents answer. The interviewer's final summary becomes the "
        "decision. Useful for spec extraction, requirement gathering, "
        "or fact-finding -- not adversarial."
    ),
    actors=["interviewer", "respondent"],
    phases=[
        DebatePhase(
            name="questions",
            actors=["interviewer"],
            description=(
                "Interviewer submits one proposal per question; "
                "Debate.context carries the topic. Each proposal title is "
                "the question; description is the rationale for asking."
            ),
            expected_actions=["kb_propose (interviewer)"],
        ),
        DebatePhase(
            name="answers",
            actors=["respondent"],
            description=(
                "Respondent critiques each question-proposal with "
                "verdict=support|modify; the critique reasoning IS the answer."
            ),
            expected_actions=["kb_critique (respondent)"],
        ),
        DebatePhase(
            name="summary",
            actors=["interviewer"],
            description="Interviewer resolves with a synthesis decision summarising answers.",
            expected_actions=["kb_resolve_debate"],
        ),
    ],
    stop_condition="interviewer calls resolve_debate",
)


_PEER_REVIEW = DebateFormat(
    name="peer_review",
    summary=(
        "Author submits a single proposal; N reviewers each critique it; "
        "an editor decides accept / minor-revisions / reject. Mirrors "
        "academic peer review. Best fit for fix-swarm proposals before "
        "they're applied."
    ),
    actors=["author", "reviewer", "editor"],
    phases=[
        DebatePhase(
            name="submission",
            actors=["author"],
            description="Author submits exactly ONE proposal.",
            expected_actions=["kb_propose (author)"],
        ),
        DebatePhase(
            name="reviews",
            actors=["reviewer"],
            description=(
                "Each reviewer critiques the proposal; verdict in "
                "{support, oppose, modify}. Multiple critiques per reviewer allowed."
            ),
            expected_actions=["kb_critique"],
        ),
        DebatePhase(
            name="decision",
            actors=["editor"],
            description=(
                "Editor reads all critiques, optionally adds their own, "
                "and resolves. Decision rationale must summarise reviewer consensus."
            ),
            expected_actions=["kb_resolve_debate (editor)"],
        ),
    ],
    stop_condition="editor calls resolve_debate",
    notes="Wire fix-swarm `propose_fix` -> peer_review debate; editor = swarm-orchestrator.",
)


_BRAINSTORMING = DebateFormat(
    name="brainstorming",
    summary=(
        "Generative: every participant submits as many proposals as they "
        "want, no critiques during proposal phase, then the group "
        "consolidates. Optimised for breadth, not selection."
    ),
    actors=["contributor", "consolidator"],
    phases=[
        DebatePhase(
            name="diverge",
            actors=["contributor"],
            description=(
                "Anyone may submit any number of proposals. Critiques are "
                "DISALLOWED here -- the goal is breadth without selection pressure."
            ),
            expected_actions=["kb_propose"],
        ),
        DebatePhase(
            name="converge",
            actors=["consolidator"],
            description=(
                "Consolidator critiques to merge near-duplicates and submits a "
                "unified proposal listing the surviving distinct ideas."
            ),
            expected_actions=["kb_critique", "kb_propose"],
        ),
        DebatePhase(
            name="select",
            actors=["consolidator"],
            description="Vote on the consolidated proposal vs the originals; resolve.",
            expected_actions=["kb_vote", "kb_resolve_debate"],
        ),
    ],
    stop_condition="consolidator calls resolve_debate",
    notes="No verdict=oppose during 'diverge' -- enforce in the agent, not the engine.",
)


_COUNCIL = DebateFormat(
    name="council",
    summary=(
        "Formal multi-stakeholder body: each council member has a fixed "
        "vote weight; chair has tie-break authority. Use for strategic "
        "decisions with clear ownership (e.g. ADRs touching multiple "
        "subsystems)."
    ),
    actors=["member", "chair"],
    phases=[
        DebatePhase(
            name="motion",
            actors=["member", "chair"],
            description="A member submits a motion as a proposal. The chair may amend.",
            expected_actions=["kb_propose"],
        ),
        DebatePhase(
            name="discussion",
            actors=["member"],
            description="Members critique the motion; verdict=support|oppose|modify.",
            expected_actions=["kb_critique"],
        ),
        DebatePhase(
            name="ballot",
            actors=["member", "chair"],
            description="Each member votes; chair votes only on a tie.",
            expected_actions=["kb_vote"],
        ),
        DebatePhase(
            name="ruling",
            actors=["chair"],
            description="Chair resolves; decision rationale must list dissenters explicitly.",
            expected_actions=["kb_resolve_debate"],
        ),
    ],
    stop_condition="chair calls resolve_debate",
)


_MENTORSHIP = DebateFormat(
    name="mentorship",
    summary=(
        "Mentor coaches a mentee through a decision via guided questions. "
        "The mentee proposes, the mentor critiques to teach, and the "
        "mentee resolves. Use for onboarding new expert YAMLs to a "
        "domain or for documenting reasoning chains."
    ),
    actors=["mentee", "mentor"],
    phases=[
        DebatePhase(
            name="initial_proposal",
            actors=["mentee"],
            description="Mentee submits their first attempt as a proposal.",
            expected_actions=["kb_propose (mentee)"],
        ),
        DebatePhase(
            name="guidance",
            actors=["mentor"],
            description=(
                "Mentor critiques with verdict=modify (rarely oppose). "
                "Critique reasoning teaches what to adjust and why."
            ),
            expected_actions=["kb_critique (mentor)"],
        ),
        DebatePhase(
            name="revised_proposal",
            actors=["mentee"],
            description="Mentee submits a revised proposal incorporating the mentor's feedback.",
            expected_actions=["kb_propose (mentee, revised)"],
        ),
        DebatePhase(
            name="resolve",
            actors=["mentee"],
            description="Mentee resolves selecting their revised proposal; mentor may add a final note.",
            expected_actions=["kb_resolve_debate (mentee)"],
        ),
    ],
    stop_condition="mentee calls resolve_debate",
)


_NEGOTIATION = DebateFormat(
    name="negotiation",
    summary=(
        "Two parties bargain toward a shared agreement. Each round, both "
        "sides amend their proposal closer to the other; deal closes when "
        "the diff between proposals is acceptable. Use for resource "
        "allocation, API contract negotiations between modules."
    ),
    actors=["party_a", "party_b"],
    phases=[
        DebatePhase(
            name="opening_offers",
            actors=["party_a", "party_b"],
            description="Each party submits its initial position as a proposal.",
            expected_actions=["kb_propose"],
        ),
        DebatePhase(
            name="rounds",
            actors=["party_a", "party_b"],
            description=(
                "Each round: both parties critique the other's latest "
                "proposal (modify only -- oppose breaks the negotiation) "
                "AND submit an amended proposal moving toward agreement."
            ),
            expected_actions=["kb_critique", "kb_propose (amended)"],
        ),
        DebatePhase(
            name="close",
            actors=["party_a", "party_b"],
            description=(
                "When both parties post a proposal with substantively "
                "identical terms, either party resolves with that proposal. "
                "Deadline cap = 5 rounds before facilitator declares no-deal."
            ),
            expected_actions=["kb_resolve_debate"],
        ),
    ],
    stop_condition="either party resolves OR 5-round cap with no convergence",
    notes="Verdict=oppose is reserved for breaking the negotiation entirely.",
)


_FORMATS: dict[str, DebateFormat] = {
    f.name: f for f in (
        _OPEN, _WITH_JUDGE, _TRIAL, _MEDIATION,
        _ONE_ON_ONE, _EXPERT_PANEL, _ROUND_TABLE, _INTERVIEW,
        _PEER_REVIEW, _BRAINSTORMING, _COUNCIL, _MENTORSHIP, _NEGOTIATION,
    )
}

# Guards `register_format`'s read-then-write so two callers can't both
# pass the existence check and both insert. List/get are read-only on a
# CPython dict -- atomic under the GIL -- so they don't need the lock.
_registry_lock = threading.RLock()


def list_formats() -> list[str]:
    """Return all registered format names."""
    return sorted(_FORMATS)


def get_format(name: str) -> DebateFormat:
    """Return the format spec for `name`. Raises ValueError if unknown."""
    if name not in _FORMATS:
        raise ValueError(
            f"unknown debate format {name!r}; choose from {list_formats()}"
        )
    return _FORMATS[name]


def is_known_format(name: str) -> bool:
    return name in _FORMATS


def register_format(fmt: DebateFormat, *, overwrite: bool = False) -> None:
    """Register a new format. Raises if name exists and overwrite is False.

    Reserved for tools that ship their own protocols (e.g. spec-swarm
    might add a hardware-arbitration format). Thread-safe -- the
    existence check and the insert run under one lock.
    """
    with _registry_lock:
        if fmt.name in _FORMATS and not overwrite:
            raise ValueError(
                f"format {fmt.name!r} already registered; "
                "pass overwrite=True to replace"
            )
        _FORMATS[fmt.name] = fmt
