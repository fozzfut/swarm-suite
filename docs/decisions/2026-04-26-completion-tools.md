# 2026-04-26 -- Self-direction completion tools (Bucket A)

## Status

Implemented. `swarm-core` ships `swarm_core.coordination.CompletionTracker`
and `swarm_core.models.completion`. `swarm-kb` ships
`swarm_kb.completion_store.CompletionStore` and four MCP tools:
`kb_subtask_done`, `kb_complete_task`, `kb_record_think`, `kb_get_completion`.
32 tests; full swarm-core + swarm-kb suite (149 tests) passes.

## Context

The fix/review/doc swarms today rely on the AI client to decide when an
expert is "done". That makes loop termination opaque: the host process
cannot stop on a clean signal, retries can spin, and there is no
auditable record of what the agent itself thought it accomplished. The
kyegomez/swarms project solves this with `max_loops="auto"` plus
explicit `complete_task` / `subtask_done` tool calls and three hard caps
(`MAX_SUBTASK_ITERATIONS`, `MAX_SUBTASK_LOOPS`, `max_consecutive_thinks`).

## Decision

Add a generic per-session completion state machine in `swarm-core`
(in-memory, thread-safe) and a persistence wrapper in `swarm-kb` that
stores `completion.json` next to `meta.json` and mirrors events into
`events.jsonl` when the session keeps a timeline.

Expose four MCP tools on swarm-kb so any tool-swarm expert can self-signal:

- `kb_subtask_done(tool, session_id, subtask_id, summary, outputs)` --
  idempotent on `subtask_id`. Re-marking the same id bumps a loop
  counter and trips `max_subtask_loops` (default 10). New ids trip
  `max_subtasks` (default 50).
- `kb_complete_task(tool, session_id, summary, outputs)` -- idempotent;
  re-call returns the existing record without overwriting.
- `kb_record_think(tool, session_id)` -- bumps the consecutive-thinks
  counter; trips `max_consecutive_thinks` (default 2). Reset by any
  subtask/completion call or by `record_action` on the in-memory tracker.
- `kb_get_completion(tool, session_id)` -- read-only; returns state,
  caps, and `should_stop` with a reason.

Cap exceedances raise `CapExceededError`, a `ValueError` subclass that
the existing `mcp_safe` wrapper maps to `INVALID_PARAMS` so the client
gets a machine-readable code with the next-step message embedded.

## Rationale

**Why split memory (swarm-core) from disk (swarm-kb).** Mirrors the
existing ClaimRegistry pattern (per CLAUDE.md DRY table). The tracker
owns cap semantics and is unit-testable without touching the filesystem;
the store owns persistence and event mirroring. Tools that don't need
disk persistence (e.g. transient in-process coordination) can use the
tracker directly.

**Why idempotent on identity, not on content.** Re-emitting the same
subtask id keeps the original `summary` and `outputs` -- the first claim
wins. Without this, an over-eager retry could rewrite an authoritative
summary; with it, the audit trail is stable.

**Why a separate `consecutive_thinks` counter.** The two existing caps
(`max_subtasks`, `max_subtask_loops`) catch agents that keep claiming
progress. The thinks counter catches the inverse: an agent that
hesitates indefinitely without claiming any progress. All three are
needed; any one alone has a clear bypass.

**Why CapExceededError is a ValueError subclass.** The `to_mcp_error`
helper maps `ValueError` to `INVALID_PARAMS`. We want clients to see
"you (the caller) need to stop" rather than "the server crashed", so
inheriting from ValueError is the simplest fix without extending the
error mapper.

**Why `kb_*` tools take both `tool` and `session_id`.** Sessions live at
`~/.swarm-kb/<tool>/sessions/<session_id>/`. Inferring `tool` from the
id alone would require either a server-side scan of all tool dirs or a
new lookup table; both add hidden state. Explicit > implicit.

**Why event mirroring is opt-in (only if `events.jsonl` exists).** The
session lifecycle's `initial_files` already creates `events.jsonl` for
review/fix/doc/arch sessions that want a timeline. Sessions without one
(e.g. transient idea/plan sessions) shouldn't suddenly grow one.

## Consequences

- **Tools that adopt these signals get free observability.** Every
  subtask_done and task_completed event lands in events.jsonl, which
  any MCP resource subscriber can read.
- **The AI client can now stop on `should_stop=True` instead of guessing.**
  This unblocks Bucket D (PlannerGeneratorEvaluator loop) and Bucket E
  (DSL with completion-aware H-token gates).
- **Tools must be migrated to call these signals.** Existing tools keep
  working unchanged; this is a new opt-in surface. Migration tickets
  follow per tool (review-swarm first, fix-swarm next).
- **`stopping_conditions.py` substring detection (item #13 from the
  ranking) is no longer planned.** With first-class completion tools,
  string matching is redundant.

## Files

- `packages/swarm-core/src/swarm_core/models/completion.py` -- dataclasses
- `packages/swarm-core/src/swarm_core/coordination/completion.py` -- tracker
- `packages/swarm-core/src/swarm_core/coordination/__init__.py` -- exports
- `packages/swarm-core/src/swarm_core/models/__init__.py` -- exports
- `packages/swarm-kb/src/swarm_kb/completion_store.py` -- disk wrapper
- `packages/swarm-kb/src/swarm_kb/server.py` -- 4 new MCP tools
- `packages/swarm-core/tests/test_completion.py` -- 20 tests
- `packages/swarm-kb/tests/test_completion_store.py` -- 12 tests
