# Pipeline stages -- Idea to Release

The Swarm Suite's pipeline takes a Python project from idea through to
production-grade industrial code. Each stage produces concrete artifacts
and ends in a **user gate** (`kb_advance_pipeline`) -- there is no
auto-progression.

```
Idea -> Spec -> Arch -> Implement -> Review -> Fix -> Docs -> Hardening -> Release
```

## Stage 0a: Idea (NEW)

**Tool:** `swarm-kb` (idea capture); `arch-swarm` (early debates).
**Inputs:** the user's first English sentence.
**Outputs:** `~/.swarm-kb/sessions/idea/<sid>/idea.md` -- problem statement,
non-goals, success criteria, top 3 design alternatives.
**Gate:** user picks an alternative.

This stage exists because "I want a tool that does X" is rarely a spec.
The brainstorming pattern from superpowers (one question per turn,
2-3 design alternatives, explicit user approval before proceeding)
is the playbook.

## Stage 0b: Spec (embedded only) -- SpecSwarm

**Inputs:** datasheets, reference manuals, requirements docs.
**Outputs:** registers, pins, protocols, timing, power budget;
constraints exported to swarm-kb.
**Gate:** user reviews specs.

## Stage 1: Architecture -- ArchSwarm

**Inputs:** code (if any) + spec constraints (if any).
**Outputs:** ADRs in `~/.swarm-kb/decisions/`, debate transcripts,
coupling/complexity metrics.
**Gate:** user reviews findings + ADRs.

## Stage 2: Implementation guidance (NEW)

**Tool:** `arch-swarm` (`writing-plans` style task breakdown);
`swarm-kb` (plan storage).
**Inputs:** approved ADRs + spec constraints.
**Outputs:** `~/.swarm-kb/sessions/plan/<sid>/<feature>.md` -- task list
where each task is 2-5 minutes, includes failing test first, exact
commands, expected outputs.
**Gate:** user approves plan.

This stage is the **superpowers pattern**: every implementation plan is
executable, testable, autonomous-agent-ready. Vague tasks are not
allowed.

## Stage 3: Review -- ReviewSwarm

**Inputs:** code (just-written or existing) + ADRs as context.
**Outputs:** findings with `actual:` / `expected:` / `source_ref:`.
**Gate:** user confirms / dismisses; quality gate computed.

## Stage 4: Fix -- FixSwarm

**Inputs:** confirmed findings + test snapshot.
**Outputs:** patches with consensus, applied; regression check.
**Gate:** quality gate decides "continue" vs "stop_clean" vs
"stop_circuit_breaker".

The **review-fix loop** repeats until either the gate is clean for two
consecutive rounds OR the circuit breaker fires.

## Stage 5: Documentation -- DocSwarm

**Inputs:** code + ADRs + the diffs produced by Fix.
**Outputs:** API reference, README quality check, changelog entries,
inline doc updates, ADRs documenting which SOLID/DRY trade-off was made.
**Gate:** user reviews docs.

## Stage 6: Hardening (NEW)

**Tool:** `review-swarm` (security pass) + `fix-swarm` (security fixes)
+ a new `release-prep` set of checks in `swarm-kb`.
**Inputs:** the now-clean codebase.
**Outputs:**
  - mypy strict pass
  - test coverage >= configured threshold (default 85%)
  - security audit (`pip-audit`, secrets scan)
  - dependency hygiene (no unused, no vulnerable, no version conflicts)
  - CI workflow draft (`.github/workflows/`)
  - observability scaffolding (structured logging configured)
**Gate:** user reviews hardening report.

## Stage 7: Release (NEW)

**Tool:** `swarm-kb` (release prep).
**Inputs:** approved hardening report.
**Outputs:**
  - Version bump (semver based on the diff)
  - Changelog entry generated from session events
  - `pyproject.toml` validated for PyPI requirements
  - LICENSE present and valid
  - `dist/` built (`python -m build`)
**Gate:** user runs `twine upload` (the suite NEVER auto-publishes).

## Quality gate -- the loop in stages 3-4

See `docs/features/quality-gate.md`. Defaults:
- max_critical: 0
- max_high: 0
- max_medium: 3
- max_weighted_score: 8 (CRITICAL=4 / HIGH=3 / MEDIUM=2 / LOW=1)
- consecutive_clean_rounds: 2
- max_iterations: 7
- max_regression_rate: 10%

Configure per project with `kb_configure_quality_gate(...)`.

## Why "user gates" are mandatory

The suite never auto-advances because:
1. Every stage produces artifacts a human should sanity-check.
2. The cost of a wrong direction at stage 1 is much cheaper to fix
   than at stage 5.
3. Industrial-grade code is collaborative, not generated.
