# Layering -- import direction is the architecture

Four layers. Imports flow downward only.

```
+-------------------------------------------------------+
| Tools:  spec-swarm | arch-swarm | review-swarm |       |
|         fix-swarm  | doc-swarm                         |
+--------------------|----------------------------------+
                     v
            +----------------+
            |    swarm-kb    |   <- storage layer
            +----------------+
                     |
                     v
            +----------------+
            |   swarm-core   |   <- foundation
            +----------------+
                     |
                     v
                 stdlib + (mcp, pyyaml, click)
```

## Rules

| Layer | May import | MUST NOT import |
|-------|-----------|-----------------|
| `swarm_core` | stdlib + (`mcp`, `pyyaml`, `click`) | any other Swarm Suite package |
| `swarm_kb` | `swarm_core` + stdlib + vendor | any `*_swarm` tool |
| `*_swarm` | `swarm_core`, `swarm_kb`, vendor SDKs | each other |

## Why

- **`swarm_core` is the foundation.** No in-suite imports = it can never
  be the target of a circular dependency, and a tool that needs it never
  pays for code it doesn't use.
- **`swarm_kb` is storage.** Tools depend on its public types, not on
  filesystem paths. Replacing the storage backend (e.g. SQLite-backed
  `findings.db` instead of JSONL) means changing one package, not five.
- **Tools never know about each other.** All cross-tool data flows
  through `swarm-kb` (findings, decisions, debates). This means: any
  tool can be removed, swapped, or replaced without breaking the
  others -- the swarm composition is loose-coupled at the package level.

## Enforcement

`scripts/check_imports.py` parses every `*.py` under `packages/<name>/src`
with `ast.parse`. Any forbidden import is reported with file:line. The
script is intended to run in CI before merge.

Known violations are recorded in `GRANDFATHERED` (with a corresponding
`docs/decisions/` entry) so the gate stays green while real code is
migrated.

## When you need cross-tool functionality

If two tools need the same code, the answer is **always** "move it down":

- Used by 2+ tools, no IO -> `swarm_core` (e.g. `Severity` enum, `MessageBus`).
- Used by 2+ tools, touches `~/.swarm-kb/` -> `swarm_kb` (e.g. `FindingWriter`).
- Used by 1 tool only -> stays in that tool.

If you find yourself reaching for `from arch_swarm import ...` inside
`fix_swarm`, stop. Open `docs/decisions/<date>-<slug>.md`, write what
needs to move and why, then either move it or grandfather the import
with a link to the decision.
