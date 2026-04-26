---
title: Finding Store
type: api
status: draft
source_files:
- src/review_swarm/finding_store.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/finding_store.py
lines_of_code: 283
classes:
- FindingStore
functions: []
---

# Finding Store

FindingStore -- Append-only JSONL storage with in-memory index for findings.

**Source:** `src/review_swarm/finding_store.py` | **Lines:** 283

## Dependencies

- `__future__`
- `collections`
- `copy`
- `json`
- `logging_config`
- `models`
- `os`
- `pathlib`
- `tempfile`
- `threading`

## Classes

### `class FindingStore`

Append-only JSONL storage with in-memory index for findings.

Each finding is stored as one JSON line in the JSONL file.
An in-memory dict provides fast lookup/filtering.

**Lines:** 19-283

**Methods:**

- `def post(self, finding: Finding) -> str` — Store a new finding. Sets timestamps, appends to JSONL.
- `def get(self, *, severity: str | None=None, category: str | None=None, status: str | None=None, file: str | None=None, expert_role: str | None=None, min_confidence: float | None=None, limit: int=0, offset: int=0) -> list[Finding]` — Return findings matching all provided filters.
- `def get_by_id(self, finding_id: str) -> Finding | None` — Return a finding by its ID, or None if not found.
- `def count(self) -> int` — Return total number of findings.
- `def count_by_severity(self) -> dict[str, int]` — Return counts grouped by severity value.
- `def count_by_status(self) -> dict[str, int]` — Return counts grouped by status value.
- `def find_duplicates(self, file: str, line_start: int, line_end: int, title: str, exclude_id: str='') -> list[Finding]` — Find potential duplicate findings by overlapping location and similar title.
- `def update_status(self, finding_id: str, status: Status) -> None` — Update the status of a finding. Marks store as dirty for deferred flush.
- `def add_reaction(self, finding_id: str, reaction_dict: dict) -> None` — Append a reaction dict to a finding's reactions list. Marks dirty.
- `def add_comment(self, finding_id: str, comment_dict: dict) -> None` — Append a comment dict to a finding's comments list. Marks dirty.
- `def add_related(self, finding_id: str, related_id: str) -> None` — Append a related finding ID if not already present. Marks dirty.
- `def flush_if_dirty(self) -> None` — Flush to disk only if in-memory state has been modified.
