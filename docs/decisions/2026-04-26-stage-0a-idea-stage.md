# 2026-04-26 -- Stage 0a "Idea" implementation contract

## Status

Specified. Not yet implemented in code. Adoption deferred to a follow-up
phase; this doc is the contract that future implementation must satisfy.

## Why

The current pipeline starts at Spec or Architecture, assuming the user
already knows what they want to build. Greenfield work doesn't have a
spec yet -- the most expensive question ("am I solving the right problem
with a reasonable approach?") gets skipped.

The `brainstorming` skill (now in `swarm_core/skills/brainstorming.md`)
is the methodology. This doc specifies the storage + tool surface that
hosts it.

## Tool surface (new)

```
kb_start_idea_session(project_path: str, prompt: str) -> {sid: str, ...}
kb_capture_idea_answer(sid: str, question: str, answer: str) -> {...}
kb_record_alternatives(sid: str, alternatives: list[dict], chosen_id: str) -> {...}
kb_finalize_idea_design(sid: str, design_md: str) -> {path: str}
```

`brainstorming` skill drives the AI's behavior through the calls; the
suite stores the outputs.

## Storage layout

```
~/.swarm-kb/sessions/idea/<sid>/
+-- meta.json                 schema_version: 1, status, prompt
+-- answers.md                appended Q&A from Phase 1
+-- alternatives.md           Phase 2: 2-3 designs + chosen
+-- design.md                 Phase 3: consolidated design
+-- events.jsonl              session events
```

`<sid>` follows the `idea-YYYY-MM-DD-NNN` convention via
`SessionLifecycle` from `swarm_core.sessions`.

## Pipeline integration

A new `STAGE_ORDER` entry: `["idea", "spec", "arch", ...]` (idea first).
For projects that skip ideation (existing codebases), `kb_start_pipeline`
takes a flag `start_at="arch"` -- exactly how `include_spec=True` already
works for Stage 0/Spec.

After Phase 5 (Planning Handoff), the `design.md` becomes input to
`arch-swarm`'s first debate (or directly to Stage 2 Plan if architecture
is trivially derived).

## Gate behavior

- `kb_advance_pipeline` from `idea` -> `arch` requires `design.md` present
  AND `meta.status` == `"design_approved"`.
- The user marks the session approved via
  `kb_finalize_idea_design(sid, design_md)`; that call sets the status.

## Acceptance for the implementation phase

1. `kb_start_idea_session` and friends exist as MCP tools.
2. `SessionLifecycle` subclass `IdeaSessionLifecycle` (tool_name=`idea`,
   session_prefix=`idea`, initial_files=`("answers.md", "alternatives.md",
   "events.jsonl")`).
3. Pipeline `STAGE_ORDER` includes `"idea"` and `STAGE_INFO["idea"]` is
   populated with brainstorming-skill-aware actions.
4. Tests: `kb_start_idea_session` -> `kb_finalize_idea_design` ->
   `kb_advance_pipeline` round-trip.

## Why not implement now

- The brainstorming skill is the hard part; it now lives in
  `swarm_core/skills/`. Wiring it to MCP tools is mechanical but touches
  multiple packages and risks breaking the existing pipeline if done
  hastily.
- A clean implementation requires bumping `swarm-kb` minor + introducing
  the `idea` tool group; that's a release event, not a refactor.
- Doing this AFTER the swarm-core extraction migration (see
  `2026-04-26-swarm-core-extraction.md`) keeps the diff reviewable.
