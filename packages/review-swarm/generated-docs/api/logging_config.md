---
title: Logging Config
type: api
status: draft
source_files:
- src/review_swarm/logging_config.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/logging_config.py
lines_of_code: 30
classes: []
functions:
- setup_logging
- get_logger
---

# Logging Config

Centralized logging configuration for ReviewSwarm.

**Source:** `src/review_swarm/logging_config.py` | **Lines:** 30

## Dependencies

- `__future__`
- `logging`
- `sys`

## Functions

### `def setup_logging(level: str='INFO') -> logging.Logger`

Configure and return the root ReviewSwarm logger.

**Lines:** 9-25

### `def get_logger(name: str) -> logging.Logger`

Get a child logger under the review_swarm namespace.

**Lines:** 28-30
