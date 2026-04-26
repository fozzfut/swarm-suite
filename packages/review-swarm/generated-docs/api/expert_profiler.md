---
title: Expert Profiler
type: api
status: draft
source_files:
- src/review_swarm/expert_profiler.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/expert_profiler.py
lines_of_code: 174
classes:
- ExpertProfiler
functions: []
---

# Expert Profiler

Expert profile loading and project analysis for expert suggestions.

**Source:** `src/review_swarm/expert_profiler.py` | **Lines:** 174

## Dependencies

- `__future__`
- `logging_config`
- `pathlib`
- `re`
- `yaml`

## Classes

### `class ExpertProfiler`

**Lines:** 16-174

**Methods:**

- `def list_profiles(self) -> list[dict]`
- `def load_profile(self, name: str) -> dict`
- `def suggest_experts(self, project_path: str) -> list[dict]`
