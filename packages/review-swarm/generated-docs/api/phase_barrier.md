---
title: Phase Barrier
type: api
status: draft
source_files:
- src/review_swarm/phase_barrier.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/phase_barrier.py
lines_of_code: 171
classes:
- PhaseBarrier
functions: []
---

# Phase Barrier

PhaseBarrier -- synchronizes multi-agent two-pass review workflow.

Tracks which agents have completed which phase. An agent marks itself
as done with a phase, then checks if all registered agents have also
finished. Phase 2 cannot start until all agents complete Phase 1.

Persisted to phases.json in the session directory.

**Source:** `src/review_swarm/phase_barrier.py` | **Lines:** 171

## Dependencies

- `__future__`
- `json`
- `logging_config`
- `models`
- `os`
- `pathlib`
- `tempfile`
- `threading`

## Classes

### `class PhaseBarrier`

Per-session phase synchronization barrier.

Phases:
    1 = "review"      -- each expert reviews files, posts findings
    2 = "cross_check"  -- each expert reads others' findings, reacts
    3 = "report"       -- generate final report, end session

An agent calls mark_phase_done(expert_role, phase) when it finishes.
An agent calls check_phase_ready(phase) to see if all agents are done
with the previous phase.

**Lines:** 24-171

**Methods:**

- `def register_agent(self, expert_role: str) -> None` — Register an agent as a participant in this session.
- `def registered_agents(self) -> set[str]`
- `def mark_phase_done(self, expert_role: str, phase: int) -> dict` — Mark that an agent has completed a phase.
- `def check_phase_ready(self, phase: int) -> dict` — Check if a phase can be started (previous phase fully complete).
- `def get_status(self) -> dict` — Get full phase status for all agents.
