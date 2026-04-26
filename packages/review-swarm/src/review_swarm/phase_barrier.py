"""PhaseBarrier -- synchronizes multi-agent two-pass review workflow.

Tracks which agents have completed which phase. An agent marks itself
as done with a phase, then checks if all registered agents have also
finished. Phase 2 cannot start until all agents complete Phase 1.

Persisted to phases.json in the session directory.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from .logging_config import get_logger
from .models import now_iso

_log = get_logger("phase_barrier")


class PhaseBarrier:
    """Per-session phase synchronization barrier.

    Phases:
        1 = "review"      -- each expert reviews files, posts findings
        2 = "cross_check"  -- each expert reads others' findings, reacts
        3 = "report"       -- generate final report, end session

    An agent calls mark_phase_done(expert_role, phase) when it finishes.
    An agent calls check_phase_ready(phase) to see if all agents are done
    with the previous phase.
    """

    def __init__(self, session_id: str, phases_path: Path) -> None:
        self._session_id = session_id
        self._path = Path(phases_path)
        self._lock = threading.Lock()
        self._agents: set[str] = set()
        self._phase_completions: dict[int, dict[str, str]] = {}  # phase -> {agent: timestamp}
        self._load()

    def register_agent(self, expert_role: str) -> None:
        """Register an agent as a participant in this session."""
        with self._lock:
            self._agents.add(expert_role)
            self._save()

    def registered_agents(self) -> set[str]:
        with self._lock:
            return set(self._agents)

    def mark_phase_done(self, expert_role: str, phase: int) -> dict:
        """Mark that an agent has completed a phase.

        Returns status dict with:
        - phase: the phase number
        - agent: the expert_role
        - all_done: True if all registered agents have completed this phase
        - waiting_for: list of agents still working on this phase
        """
        with self._lock:
            if expert_role not in self._agents:
                self._agents.add(expert_role)

            if phase not in self._phase_completions:
                self._phase_completions[phase] = {}

            self._phase_completions[phase][expert_role] = now_iso()
            self._save()

            done = set(self._phase_completions[phase].keys())
            waiting = self._agents - done
            return {
                "phase": phase,
                "agent": expert_role,
                "completed_count": len(done),
                "total_agents": len(self._agents),
                "all_done": len(waiting) == 0,
                "waiting_for": sorted(waiting),
            }

    def check_phase_ready(self, phase: int) -> dict:
        """Check if a phase can be started (previous phase fully complete).

        Phase 1 is always ready.
        Phase N is ready when all agents have completed phase N-1.
        """
        with self._lock:
            if phase <= 1:
                return {
                    "phase": phase,
                    "ready": True,
                    "waiting_for": [],
                }

            prev_phase = phase - 1
            prev_completions = self._phase_completions.get(prev_phase, {})
            done = set(prev_completions.keys())
            waiting = self._agents - done

            return {
                "phase": phase,
                "ready": len(waiting) == 0,
                "completed_previous": len(done),
                "total_agents": len(self._agents),
                "waiting_for": sorted(waiting),
            }

    def get_status(self) -> dict:
        """Get full phase status for all agents."""
        with self._lock:
            phases = {}
            for phase_num, completions in sorted(self._phase_completions.items()):
                done = set(completions.keys())
                waiting = self._agents - done
                phases[phase_num] = {
                    "completed": sorted(done),
                    "waiting_for": sorted(waiting),
                    "all_done": len(waiting) == 0,
                }
            return {
                "session_id": self._session_id,
                "registered_agents": sorted(self._agents),
                "phases": phases,
            }

    # ── Persistence ──────────────────────────────────────────────────

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "agents": sorted(self._agents),
            "phases": {
                str(k): v for k, v in self._phase_completions.items()
            },
        }
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp")
        try:
            fh = os.fdopen(tmp_fd, "w", encoding="utf-8")
        except Exception:
            os.close(tmp_fd)
            os.unlink(tmp_path)
            raise
        try:
            with fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp_path, str(self._path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            text = self._path.read_text(encoding="utf-8").strip()
            if not text:
                return
            data = json.loads(text)
            self._agents = set(data.get("agents", []))
            self._phase_completions = {
                int(k): v for k, v in data.get("phases", {}).items()
            }
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            _log.warning("Corrupt phases file %s, starting fresh: %s", self._path, exc)
