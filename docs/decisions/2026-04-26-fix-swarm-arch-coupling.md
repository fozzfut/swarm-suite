# 2026-04-26 -- fix-swarm reaches into arch-swarm for project scanning

## Status

Open. Grandfathered in `scripts/check_imports.py::GRANDFATHERED`.

## Context

`packages/fix-swarm/src/fix_swarm/arch_adapter.py:93` calls
`from arch_swarm.code_scanner import scan_project, ArchAnalysis`. This is a
direct cross-tool import and violates the layering rule in CLAUDE.md
("`*_swarm` packages MUST NOT import from each other").

The dependency exists because both ArchSwarm and FixSwarm need the same AST
scanner -- and historically the scanner was first written inside ArchSwarm.

## Decision

Move the AST scanner into `swarm_core.code_scan` (new submodule). Both
`arch_swarm` and `fix_swarm` will then depend on the shared scanner via
`swarm_core`, restoring the layering invariant.

## Migration plan

1. Extract `arch_swarm.code_scanner` into a new `swarm_core.code_scan`
   subpackage with the public surface used by FixSwarm:
   `scan_project(path, scope=None) -> ScanResult`.
2. Add a thin `arch_swarm.code_scanner` shim that re-exports from
   `swarm_core.code_scan` (preserves any external callers).
3. Update `fix_swarm.arch_adapter` to import from `swarm_core.code_scan`.
4. Remove the entry from `GRANDFATHERED` in `check_imports.py`.

## Why grandfather instead of fix now

The fix is mechanical but touches three packages and needs a `swarm-core`
release. Splitting it out as a separate phase keeps the consolidation /
SOLID-DRY refactor PRs reviewable. Tracked here so the violation can't
silently grow.
