---
title: Claim Registry
type: api
status: draft
source_files:
- src/review_swarm/claim_registry.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/claim_registry.py
lines_of_code: 139
classes:
- ClaimRegistry
functions: []
---

# Claim Registry

ClaimRegistry -- Advisory file claim tracking with TTL-based expiry.

**Source:** `src/review_swarm/claim_registry.py` | **Lines:** 139

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

### `class ClaimRegistry`

Tracks which agent is working on which file.

Claims are soft/advisory -- they prevent duplicate work but are not
enforced locks.  Each claim has a TTL; expired claims are filtered
out on read.  State is persisted as a JSON array to disk.

**Lines:** 17-139

**Methods:**

- `def claim(self, session_id: str, file: str, expert_role: str, agent_id: str) -> Claim` — Claim a file for review.
- `def release(self, session_id: str, file: str, expert_role: str) -> None` — Release a claim by marking it as 'released'.
- `def release_all(self, session_id: str) -> None` — Release all active claims for a session.
- `def get_claims(self, session_id: str) -> list[Claim]` — Return active, non-expired claims for a session.
