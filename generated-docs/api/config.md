---
title: Config
type: api
status: draft
source_files:
- src/review_swarm/config.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/config.py
lines_of_code: 133
classes:
- ConsensusConfig
- ExpertsConfig
- RateLimitConfig
- Config
functions: []
---

# Config

Global configuration loading.

**Source:** `src/review_swarm/config.py` | **Lines:** 133

## Dependencies

- `__future__`
- `dataclasses`
- `pathlib`
- `yaml`

## Classes

### `class ConsensusConfig`

**Lines:** 12-14

### `class ExpertsConfig`

**Lines:** 18-20

### `class RateLimitConfig`

**Lines:** 24-26

### `class Config`

**Lines:** 30-133

**Methods:**

- `def storage_path(self) -> Path`
- `def sessions_path(self) -> Path`
- `def custom_experts_path(self) -> Path`
- `def load(cls, path: Path | None=None) -> Config`
- `def to_yaml(self) -> str` — Serialize config to YAML string.
