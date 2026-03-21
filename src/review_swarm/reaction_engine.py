"""ReactionEngine -- Consensus-based status updates for findings."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .finding_store import FindingStore
from .models import Finding, Reaction, ReactionType, Status, now_iso


class ReactionEngine:
    """Processes reactions and auto-updates finding status via consensus rules.

    Consensus rules:
        - 1+ "duplicate" reactions -> status: DUPLICATE, bidirectional link
        - 1+ "dispute" reactions   -> status: DISPUTED (overrides confirms)
        - N+ "confirm", 0 dispute  -> status: CONFIRMED (N = confirm_threshold)
        - otherwise                -> status: OPEN
        - "extend" reactions       -> no status change, bidirectional link

    Lock ordering: ReactionEngine._lock is always acquired BEFORE FindingStore._lock.
    Never acquire ReactionEngine._lock while holding FindingStore._lock.
    """

    def __init__(
        self,
        store: FindingStore,
        reactions_path: Path,
        confirm_threshold: int = 2,
    ) -> None:
        self._store = store
        self._reactions_path = Path(reactions_path)
        self._confirm_threshold = confirm_threshold
        self._lock = threading.Lock()

    def react(self, reaction: Reaction) -> Finding:
        """Process a reaction against a finding.

        1. Look up finding by reaction.finding_id (raise KeyError if not found)
        2. Set reaction.created_at
        3. Append reaction to reactions.jsonl
        4. Add reaction dict to finding via store.add_reaction()
        5. Handle linking for duplicate/extend (bidirectional via store.add_related())
        6. Recompute status via _recompute_status()
        7. Return updated finding
        """
        with self._lock:
            # 1. Look up finding
            finding = self._store.get_by_id(reaction.finding_id)
            if finding is None:
                raise KeyError(f"Finding {reaction.finding_id} not found")

            # Check for duplicate reaction from same expert
            for existing in finding.reactions:
                if (existing.get("expert_role") == reaction.expert_role
                    and existing.get("reaction") == reaction.reaction.value):
                    raise ValueError(
                        f"Duplicate reaction: {reaction.expert_role} already "
                        f"{reaction.reaction.value}d finding {reaction.finding_id}"
                    )

            # 2. Set timestamp
            reaction.created_at = now_iso()

            # 3. Append to reactions.jsonl
            self._reactions_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._reactions_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(reaction.to_dict()) + "\n")

            # 4. Add reaction dict to finding
            self._store.add_reaction(finding.id, reaction.to_dict())

            # 5. Handle linking for duplicate/extend
            if reaction.reaction in (ReactionType.DUPLICATE, ReactionType.EXTEND):
                if reaction.related_finding_id:
                    # Bidirectional link
                    self._store.add_related(finding.id, reaction.related_finding_id)
                    self._store.add_related(reaction.related_finding_id, finding.id)

            # 6. Recompute status
            self._recompute_status(finding)

            # 7. Return updated finding
            return finding

    def _recompute_status(self, finding: Finding) -> None:
        """Recompute finding status from its reactions list.

        Priority: duplicate > dispute > confirmed > open
        """
        # Snapshot reactions while still holding self._lock
        reactions = list(finding.reactions)
        confirms = 0
        disputes = 0
        duplicates = 0

        for r in reactions:
            rtype = r.get("reaction", "")
            if rtype == ReactionType.CONFIRM.value:
                confirms += 1
            elif rtype == ReactionType.DISPUTE.value:
                disputes += 1
            elif rtype == ReactionType.DUPLICATE.value:
                duplicates += 1

        # Priority: duplicate > dispute > confirmed > open
        if duplicates > 0:
            new_status = Status.DUPLICATE
        elif disputes > 0:
            new_status = Status.DISPUTED
        elif confirms >= self._confirm_threshold and disputes == 0:
            new_status = Status.CONFIRMED
        else:
            new_status = Status.OPEN

        if finding.status != new_status:
            self._store.update_status(finding.id, new_status)
