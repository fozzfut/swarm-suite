# 2026-04-26 -- Stage 2 "Plan" implementation contract

## Status

Specified. Not yet implemented. Adoption deferred to follow-up phase.

## Why

ADRs from arch-swarm tell you WHAT to build; they don't tell you what
order to build it in, what tests to write first, or what to commit
between steps. Without a plan stage, the executing agent guesses --
which is exactly what the `writing_plans` skill was designed to prevent.

The `writing_plans` skill (now in `swarm_core/skills/writing_plans.md`)
is the methodology. This doc specifies the storage + tool surface.

## Tool surface (new)

```
kb_start_plan_session(project_path: str, adr_ids: list[str]) -> {sid: str, ...}
kb_emit_task(sid: str, task_md: str) -> {task_id: str}
kb_finalize_plan(sid: str, plan_md: str) -> {path: str}
```

The `writing_plans` skill drives the AI's behavior; the suite stores
each emitted task and assembles the final plan.

## Storage layout

```
~/.swarm-kb/sessions/plan/<sid>/
+-- meta.json                 schema_version: 1, adr_ids
+-- tasks.jsonl               one JSON per emitted task
+-- plan.md                   final assembled plan (Markdown)
+-- events.jsonl
```

`<sid>` = `plan-YYYY-MM-DD-NNN` via `SessionLifecycle`.

## Plan document constraints (validated)

The MCP tool `kb_finalize_plan` validates the plan markdown against the
`writing_plans` skill's contract:

1. Header present (Goal / Architecture / Tech stack / ADR refs).
2. Every task has Steps 1-5 (failing test -> verify fail -> implement ->
   verify pass -> commit).
3. Every step in Steps 2/4 includes an exact command + expected output.
4. Every Step 5 includes a `git commit -m` with the canonical message
   format.

If validation fails, the call returns `{"errors": [...]}` and does NOT
finalize. Caller fixes and retries.

## Pipeline integration

New stage between Architecture and Review: `STAGE_ORDER` becomes
`["idea", "spec", "arch", "plan", "review", "fix", "verify", "doc"]`.

`plan` is OPTIONAL like `spec` -- `kb_start_pipeline(include_plan=False)`
skips it. Default-on for new projects (post-Idea); default-off for
review-only workflows.

## Gate behavior

`kb_advance_pipeline` from `plan` -> `review` requires `plan.md` exists
AND validation passed. Review then operates against the changed code
that the plan produces (review-as-you-go).

## Why not implement now

Same reason as Stage 0a: scope. The skill is here; tool wiring is a
release-event, not a refactor.
