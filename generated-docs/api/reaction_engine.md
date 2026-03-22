---
title: Reaction Engine
type: api
status: draft
source_files:
- src/review_swarm/reaction_engine.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/reaction_engine.py
lines_of_code: 131
classes:
- ReactionEngine
functions: []
---

# Reaction Engine

ReactionEngine -- Consensus-based status updates for findings.

**Source:** `src/review_swarm/reaction_engine.py` | **Lines:** 131

## Dependencies

- `__future__`
- `finding_store`
- `json`
- `logging_config`
- `models`
- `pathlib`
- `threading`

## Classes

### `class ReactionEngine`

Processes reactions and auto-updates finding status via consensus rules.

Consensus rules:
    - 1+ "duplicate" reactions -> status: DUPLICATE, bidirectional link
    - 1+ "dispute" reactions   -> status: DISPUTED (overrides confirms)
    - N+ "confirm", 0 dispute  -> status: CONFIRMED (N = confirm_threshold)
    - otherwise                -> status: OPEN
    - "extend" reactions       -> no status change, bidirectional link

Lock ordering: ReactionEngine._lock is always acquired BEFORE FindingStore._lock.
Never acquire ReactionEngine._lock while holding FindingStore._lock.

**Lines:** 16-131

**Methods:**

- `def react(self, reaction: Reaction) -> Finding` — Process a reaction against a finding.
