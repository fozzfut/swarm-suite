---
title: Rate Limiter
type: api
status: draft
source_files:
- src/review_swarm/rate_limiter.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/rate_limiter.py
lines_of_code: 61
classes:
- RateLimiter
functions: []
---

# Rate Limiter

Simple sliding-window rate limiter per agent.

**Source:** `src/review_swarm/rate_limiter.py` | **Lines:** 61

## Dependencies

- `__future__`
- `collections`
- `logging_config`
- `threading`
- `time`

## Classes

### `class RateLimiter`

Per-agent sliding window rate limiter.

Tracks call timestamps per agent_key. Rejects calls that exceed
max_calls within window_seconds.

**Lines:** 14-61

**Methods:**

- `def check(self, agent_key: str) -> None` — Check if agent can make a call. Raises ValueError if rate exceeded.
- `def reset(self, agent_key: str | None=None) -> None` — Reset rate limiter for one agent or all agents.
- `def reset_prefix(self, prefix: str) -> None` — Remove all entries whose key starts with *prefix*.
