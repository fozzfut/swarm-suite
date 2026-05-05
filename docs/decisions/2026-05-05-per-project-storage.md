# Per-project storage layout (Phase 5)

**Date:** 2026-05-05
**Status:** Accepted (foundation + migration shipped; default-flip deferred to M5)
**Related code:** packages/swarm-kb/src/swarm_kb/{config,paths,finding_writer,server,migrate_per_project}.py

## Context

Up to and including Phase 4 (retrieval-augmented reasoning, ADR `adr-15bde0ae`), all swarm-kb data shared a single global pool under `~/.swarm-kb/`:

```
~/.swarm-kb/
├── arch/sessions/<sid>/             ← all projects mixed
├── review/sessions/<sid>/           ← all projects mixed
├── ...                              ← (review|fix|doc|arch|spec|idea|plan|harden|release|monitor)
├── decisions/decisions.jsonl        ← single file, all projects
├── debates/{debates.jsonl, active/} ← single file, all projects
├── pipelines/<pid>/                 ← all projects
├── code-map/<project_hash>/         ← already per-project (only one)
├── xrefs/                           ← cross-project (intentional)
└── index/kb.db                      ← single global vector index
```

Each finding / decision / debate carries a `project_path` field, but query-side filtering was *optional*. The consequences:

- **Cross-project leakage**: `kb_semantic_search("oauth flaw")` without `project_path` filter could return findings from an unrelated NDA project.
- **No project export**: backing up "everything for project X" required a custom JSONL grep.
- **Privacy**: confidential project A's findings sat in the same `decisions.jsonl` line as a public project B's.
- **Deletion**: removing a project from disk left orphaned entries behind in the global pool.
- **Vector index pressure**: a single global index grew unboundedly across all projects on the developer's machine.

The user (Ilya) explicitly chose option **C — full hybrid refactor** during the architecture discussion in this session, after I laid out four options ranging from "do nothing, document the filter requirement" to "full per-project isolation".

## Decision

Storage is partitioned per project under `~/.swarm-kb/projects/<project_hash>/`. The global root keeps only suite-wide state and intentionally-cross-project artefacts:

```
~/.swarm-kb/
├── config.yaml                      ← global suite config
├── xrefs/                           ← cross-project linkage (unchanged)
├── projects/<project_hash>/         ← ONE directory per project
│   ├── meta.json                    ← {project_path, created_at, last_used_at, migrated_from_legacy}
│   ├── arch/sessions/<sid>/
│   ├── review/sessions/<sid>/
│   ├── ...
│   ├── decisions/decisions.jsonl    ← split per project
│   ├── debates/{debates.jsonl, active/<dbt>/}
│   ├── pipelines/<pid>/
│   ├── code-map/                    ← moved here from global code-map/<hash>/
│   └── index/kb.db                  ← per-project vector index
└── (legacy global paths preserved during the migration window)
```

`project_hash_for(project_path)` produces a stable 16-char SHA-256 prefix from the resolved absolute project path (defined in `paths.py`).

The MCP server lifespan reads a `SWARM_KB_PROJECT` environment variable (or accepts a per-call `project_path` argument on every storage tool) and lazy-builds a `_ProjectState` per project. The shared embedder (~700 MB load via sentence-transformers) is built once and reused across every per-project `VectorIndex`, but the index files themselves differ per project so retrieval doesn't cross boundaries.

### What stays global

- `~/.swarm-kb/config.yaml` — suite-wide settings (storage_root, embedding provider, code_map skip_dirs)
- `~/.swarm-kb/xrefs/` — cross-references that intentionally link entities across projects (a finding in project A that's superseded by a decision in project B is a legitimate xref)
- `~/.swarm-kb/projects/` — the container for everything per-project

### What's per-project

- All session pools (one directory per tool: review, fix, arch, doc, spec, idea, plan, harden, release, monitor)
- decisions.jsonl
- debates.jsonl + active/`<dbt>`/
- pipelines/`<pid>`/
- code-map/
- index/kb.db
- Plus internal stores for judging, verification, pgve, dsl-flow

## Consequences

### Positive

- **Privacy**: confidential project findings live in their own directory tree. Backup, share, or delete one project without touching others.
- **Cross-project isolation by default**: `kb_semantic_search` on project B can't return project A's results unless the caller explicitly opts into a cross-project mode (forthcoming).
- **Manageable vector indexes**: each project's `kb.db` stays bounded. A developer with 20 projects has 20 indexes, each scoped — vs a single 20-project index where ANN parameters get harder to tune.
- **Cleaner deletion**: `rm -rf ~/.swarm-kb/projects/<hash>/` removes one project's KB completely.

### Costs

- **Migration**: existing users have legacy global state. The `swarm-kb migrate-to-per-project` CLI handles this (M4 in this session). Idempotent, supports `--dry-run`, `--keep-legacy` (copy not move), `--default-project` for entries that lack a `project_path` field, `--finalize` for cleaning up after verification.
- **Vector index rebuild**: the legacy global `index/kb.db` is dropped during migration; users run `swarm-kb vector-rebuild` once per project after migration. The migration CLI prints concrete commands.
- **One env var or per-call argument**: `SWARM_KB_PROJECT=/path/to/repo` works for single-project sessions; explicit `project_path=...` arg works for cross-project orchestration. Both supported.
- **Backwards-compat window**: through this release, empty `project_path` falls back to the legacy global pool. Will be deprecated in a follow-up release after migration adoption.

## Phasing

| Milestone | Status | Description |
|-----------|--------|-------------|
| M1 — config + path API | Shipped | `SuiteConfig.project_root(path)` + per-project path methods |
| M2 — FindingWriter project_path | Shipped | Writer accepts `project_path` kwarg; legacy default = "" |
| M3 — server lifespan + tools | Shipped | `_ProjectState` cache; 53 MCP tools accept `project_path` |
| M4 — migration CLI | Shipped | `swarm-kb migrate-to-per-project` (510 LOC, 15 tests) |
| M5 — flip defaults + docs | This commit (docs only); flip deferred | This ADR + architecture doc + GUIDE update; default-flip after migration adoption |

## Alternatives considered

- **A. Do nothing** — keep global pool, document `project_path` filter requirement on every query. Rejected: privacy and leakage are not addressed; relies on every caller to remember the filter.
- **B. Soft hardening** — global pool with default project filter applied automatically by the MCP server lifespan. Rejected: still single physical pool; deletion / backup / share-one-project still hard; doesn't address vector index growth.
- **D. Future ticket** — backlog the work, don't act. Rejected: cost-asymmetry — fixing this *after* users have accumulated significant data across multiple projects becomes a much harder migration.

## References

- Foundation commit: `073d563 feat(kb): per-project storage layout — config + migration foundation (Phase 5 M1/M2/M4)`
- Server commit: `397958b feat(kb): MCP server lifespan + tools route per-project (Phase 5 M3)`
- Vector memory ADR (Phase 1): `adr-15bde0ae` (in swarm-kb decisions)
