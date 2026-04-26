# 2026-04-26 -- swarm-core extraction roadmap

## Status

Phase 1 complete (swarm-core package built, tested, published as
canonical home). Phase 2-4 pending -- per-tool migration.

## Context

Audit (see commit history + CLAUDE.md DRY table) found these duplicated
across the 6 source packages:

| Concern | Duplication count |
|---------|-------------------|
| `Severity`, `ReactionType`, `Message`, `Event`, `Reaction`, `now_iso()` | 5 of 6 |
| `expert_profiler.py` (YAML loader + `_load_yaml`) | 4 of 6 |
| `session_manager.py` lifecycle (mkdir, meta.json, prune, list_sessions) | 4 of 6 |
| `report_generator.py` markdown helpers | 3 of 6 |
| MCP server scaffolding (transport, error wrap) | 6 of 6 |
| `logging_config.py` setup | 4 of 6 |
| ID generation (`secrets.token_hex`) | every package |

`swarm-core` is the new canonical home for all of these. Its API is
documented in `packages/swarm-core/README.md`.

## Decision

Migrate each tool in a separate phase to keep blast radius small.
Per-tool refactor steps:

1. Add `swarm-core>=0.1.0` to `dependencies` in the tool's
   `pyproject.toml`.
2. Replace tool-local `models.py` enums (`Severity`, `ReactionType`,
   `MessageType`, `EventType`) with `from swarm_core.models import ...`.
   Keep tool-specific dataclasses (`Finding`, `FixProposal`, `Register`,
   `DesignProposal`) -- those are domain types that belong per-tool.
3. Replace tool-local `expert_profiler.py` with
   `from swarm_core.experts import ExpertRegistry, <strategy>`.
   Tool wires up its own strategy choice
   (review-swarm: `ProjectScanStrategy`, fix-swarm: `FindingMatchStrategy`,
   spec-swarm: `NullSuggestStrategy` for now).
4. Replace tool-local `session_manager.py` with a subclass of
   `SessionLifecycle` plus the tool's own `*Store` composition. The
   existing `FindingStore`, `ClaimRegistry`, etc. inside review-swarm
   become thin wrappers that delegate to `swarm_core.coordination`
   instances.
5. Replace `logging_config.py` with `from swarm_core.logging_setup import
   setup_logging, get_logger`. Tool-local logger names migrate from
   `<tool>.<subsys>` to `swarm.<tool>.<subsys>`.
6. Replace the tool's MCP server entry point with `MCPApp` registration.
   Keep transport binding in the tool's `server.py`.
7. Bump tool patch version (e.g. `review-swarm 0.3.11` -> `0.4.0`
   minor bump because the public API of expert YAML loader changes,
   but tool's MCP API stays the same).
8. Run `pytest packages/<tool>/tests` and `python scripts/check_imports.py`.

## Migration order

Order matters because later tools benefit from earlier migrations'
shake-out:

1. **review-swarm** (pilot -- richest infrastructure, exposes most
   abstractions)
2. **fix-swarm** (similar shape; validates the shared Reaction/Message
   bases)
3. **doc-swarm** (similar shape; validates the markdown report helpers)
4. **arch-swarm** (lighter; mostly enum + report changes)
5. **spec-swarm** (mostly enum changes; validates `NullSuggestStrategy`)
6. **swarm-kb** (smallest delta -- only needs to drop its inline
   enum copies in favor of `swarm_core.models`)

After each migration, the tool stays releasable independently to PyPI.
The DRY constraint at the suite level means `swarm-core>=X.Y.Z` is
the floor in every tool's `pyproject.toml`; `scripts/bump_versions.py`
enforces the matrix.

## Acceptance per phase

- All tool tests pass.
- `scripts/check_imports.py` clean (no new entries in `GRANDFATHERED`).
- Tool's CLI entry point still launches the MCP server and serves the
  same set of tool names (verified by an `mcp tools/list` call in a
  smoke test).
- Per-tool `models.py` shrinks; total LOC across the suite drops.

## Why phase by phase, not big-bang

A big-bang refactor would:
- touch ~80 files at once
- require simultaneous releases of 6 packages
- block bug fixes in any of those packages until the refactor lands
- be impossible to bisect when something breaks

Phased migration keeps each step reviewable, releasable, and revertable.
