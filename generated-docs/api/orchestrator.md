---
title: Orchestrator
type: api
status: draft
source_files:
- src/review_swarm/orchestrator.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/orchestrator.py
lines_of_code: 410
classes:
- ReviewPlan
- Orchestrator
functions: []
---

# Orchestrator

Orchestrator -- single-command review planning and coordination.

Takes a scope (file pattern or directory) and a task description,
then produces a complete execution plan that an LLM agent can follow.

ReviewSwarm is infrastructure, not an LLM. The orchestrator doesn't
run agents -- it creates an optimal plan and returns it. The calling
LLM follows the plan step by step.

**Source:** `src/review_swarm/orchestrator.py` | **Lines:** 410

## Dependencies

- `__future__`
- `config`
- `dataclasses`
- `expert_profiler`
- `logging_config`
- `pathlib`
- `session_manager`

## Classes

### `class ReviewPlan`

A complete execution plan for a multi-expert code review.

**Lines:** 30-55

**Methods:**

- `def to_dict(self) -> dict`

### `class Orchestrator`

Plans and initializes a complete multi-expert review session.

**Lines:** 100-410

**Methods:**

- `def plan_review(self, project_path: str, scope: str='', task: str='', max_experts: int=5, session_name: str | None=None) -> ReviewPlan` — Create a complete review plan.
