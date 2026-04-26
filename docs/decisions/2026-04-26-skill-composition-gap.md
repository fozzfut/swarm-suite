# 2026-04-26 -- skill composition not yet flowing to AI

## Status

**RESOLVED 2026-04-26** in two phases:

**Phase A (commit ae7b8ad):** the user-facing CLI surface --
`<tool> prompt <expert>` -- now calls `compose_system_prompt()` (or
`ExpertProfile.composed_system_prompt`) for all 5 tools plus the
arch-swarm `--debate-roles` variant. Composed prompts (15-25 KB)
contain all declared + universal skill bodies. Verified by 11 CLI
smoke tests + Section 4 of `verify_e2e.py`.

**Phase B (this commit):** the per-tool `ExpertProfiler` /
`FixExpertProfiler` classes are now thin shims (40-50 lines each)
wrapping `swarm_core.experts.ExpertRegistry` while preserving the
legacy dict-shaped public API. The 180-line review-swarm and 145-line
fix-swarm YAML loaders are gone -- replaced by delegation to
swarm-core. The 7 inherited test_expert_profiler tests pass against
the shim unchanged.

What's left: the original decision proposed deleting per-tool
`expert_profiler.py` entirely and migrating callers to the dataclass
API. Phase B chose **API preservation via shim** instead because:
- Keeps callers (orchestrator, session_manager, CLI) unchanged.
- Same DRY win (no duplicate YAML loaders).
- Same runtime behavior (composition flows correctly).
- Less risk of breaking inherited tests.

## Context

`swarm_core.experts.ExpertProfile.composed_system_prompt` was added to
assemble role + declared skills + universal skills into the prompt the
AI sees. End-to-end smoke test on a sample expert produced 25 KB
composed prompts in correct order.

But the existing tools don't call `composed_system_prompt`. They call
the legacy `expert_profiler` (one per tool: `review_swarm.expert_profiler`,
`fix_swarm.expert_profiler`, ...) which loads YAML directly into a dict
and reads `profile["system_prompt"]`. Concretely:

- `packages/review-swarm/src/review_swarm/cli.py:221`:
  `sys_prompt = profile.get("system_prompt", "")`
- Same pattern in `fix-swarm`, `arch-swarm`, `doc-swarm`, `spec-swarm`.

**Effect.** Composed skill prompts (systematic_debugging, self_review,
solid_dry, karpathy_guidelines, ...) DO NOT REACH the AI. The user gets
the role-only prompt that lived in YAML before composition was added.

The composition layer is correct; nobody calls it. This is a
**Goal-Driven-Execution failure** in the sense of the
karpathy_guidelines skill: tests passed (`pytest swarm-core`), but the
real goal -- "an AI agent invoked through this suite reads the composed
prompt" -- is unmet.

## Decision

Migrate every tool from its local `expert_profiler` to
`swarm_core.experts.ExpertRegistry`. Per-tool steps:

1. Replace `from .expert_profiler import ExpertProfiler` with
   `from swarm_core.experts import ExpertRegistry, NullSuggestStrategy`
   (or the strategy that fits the tool: `ProjectScanStrategy` for
   review-swarm, `FindingMatchStrategy` for fix-swarm).
2. Where the tool reads `profile["system_prompt"]`, change to
   `profile.composed_system_prompt`.
3. Where the tool reads `profile["name"]`, change to `profile.name`;
   `profile["description"]` -> `profile.description`; etc. The
   dataclass-shape API is stricter than dict-shape.
4. Delete the per-tool `expert_profiler.py` -- its job moves entirely
   to `swarm_core.experts`. (This DRYs out 4 redundant copies.)
5. Update existing tests that depend on the per-tool API.
6. Bump tool minor: `review-swarm 0.5.0`, `fix-swarm 0.4.0`,
   `arch-swarm 0.3.0`, `doc-swarm 0.2.0`, `spec-swarm 0.2.0`.
7. Run `python scripts/test_all.py` after each tool's migration; commit
   per-tool to keep the diff bisectable.

## Acceptance

After migration completes:

- All 5 tool CLIs (`review-swarm`, `fix-swarm`, ...) produce composed
  prompts when given a YAML expert.
- The per-tool `expert_profiler.py` files are gone.
- An end-to-end smoke (start a real review-swarm session, post a
  finding, get the prompt that the AI saw) shows all 4 universal +
  declared skills present in the prompt.
- `pytest packages/review-swarm/tests` plus the others stay green.

## Why a separate phase

Each tool's `expert_profiler` is about 200 lines plus 4-8 tests. Migrating
all 5 in one PR would be ~1000 lines touched with cross-cutting test
churn. Doing them sequentially -- one PR per tool, each green at every
checkpoint -- is bisect-safe and reviewable. Order follows the
swarm-core extraction roadmap (review-swarm pilot first).

## What works in the meantime

- The skill files themselves (`swarm_core/skills/*.md`) are loaded and
  composed correctly when accessed through `ExpertProfile` directly.
- Tests prove the composition mechanism is correct.
- The MCP server already exposes new tools that don't need expert
  composition (Stage 0a/2/6/7, lite-mode, keeper, rewind).

The gap is specifically: existing review/fix/arch/doc/spec experts'
prompts as served via their CLI today don't include the new skill
overlays.
