---
title: Session Manager
type: api
status: draft
source_files:
- src/review_swarm/session_manager.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/session_manager.py
lines_of_code: 307
classes:
- SessionManager
functions: []
---

# Session Manager

Session lifecycle management.

**Source:** `src/review_swarm/session_manager.py` | **Lines:** 307

## Dependencies

- `__future__`
- `claim_registry`
- `config`
- `datetime`
- `event_bus`
- `finding_store`
- `json`
- `logging_config`
- `message_bus`
- `models`
- `pathlib`
- `phase_barrier`
- `reaction_engine`
- `report_generator`
- `shutil`
- `threading`
- `uuid`

## Classes

### `class SessionManager`

**Lines:** 25-307

**Methods:**

- `def start_session(self, project_path: str, name: str | None=None) -> str`
- `def end_session(self, session_id: str) -> dict`
- `def get_session(self, session_id: str) -> dict`
- `def list_sessions(self) -> list[dict]`
- `def get_finding_store(self, session_id: str) -> FindingStore`
- `def get_claim_registry(self, session_id: str) -> ClaimRegistry`
- `def get_reaction_engine(self, session_id: str) -> ReactionEngine`
- `def get_message_bus(self, session_id: str) -> MessageBus`
- `def get_phase_barrier(self, session_id: str) -> PhaseBarrier`
- `def get_event_bus(self, session_id: str) -> SessionEventBus`
- `def get_project_path(self, session_id: str) -> str`
