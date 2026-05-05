# Per-project storage layout

> **Status:** shipped Phase 5 M1–M4 (foundation + migration); default-flip deferred to a follow-up milestone.
> **ADR:** [docs/decisions/2026-05-05-per-project-storage.md](../decisions/2026-05-05-per-project-storage.md)

## TL;DR

`~/.swarm-kb/projects/<project_hash>/` holds everything for one project — sessions, decisions, debates, pipelines, code map, vector index. Cross-project state stays at the global root. Tools route via `SWARM_KB_PROJECT` env var or an explicit `project_path` argument. Existing data migrates with `swarm-kb migrate-to-per-project`.

## Layout

```
~/.swarm-kb/
├── config.yaml                      ← suite-wide config
├── xrefs/                           ← cross-project links (intentional)
├── projects/
│   └── <project_hash>/              ← one directory per project
│       ├── meta.json                ← {project_path, created_at, ...}
│       ├── arch/sessions/<sid>/
│       ├── review/sessions/<sid>/
│       ├── fix/sessions/<sid>/
│       ├── doc/sessions/<sid>/
│       ├── spec/sessions/<sid>/
│       ├── idea/sessions/<sid>/
│       ├── plan/sessions/<sid>/
│       ├── harden/sessions/<sid>/
│       ├── release/sessions/<sid>/
│       ├── monitor/sessions/<sid>/
│       ├── decisions/decisions.jsonl
│       ├── debates/{debates.jsonl, active/<dbt>/}
│       ├── pipelines/<pid>/
│       ├── code-map/
│       ├── judgings/active/<jud>/
│       ├── verifications/active/<ver>/
│       ├── pgve/active/<sess>/
│       ├── flows/active/<flow>/
│       └── index/kb.db              ← per-project vector index
└── (legacy global paths during migration window)
```

`project_hash_for(project_path)` (`paths.py`) gives a stable 16-char SHA-256 prefix from the resolved absolute path. Same project → same hash forever; renaming the directory invalidates the hash, which is intentional — moved projects look like new projects.

## How tools route

Every storage-touching MCP tool in swarm-kb accepts `project_path: str = ""`:

```python
kb_post_finding(tool="review", session_id="rev-1", finding="...",
                project_path="/abs/path/to/repo")

kb_semantic_search(query="...", project_path="/abs/path/to/repo")

kb_post_decision(title="...", project_path="/abs/path/to/repo", ...)
```

Resolution order in the lifespan:
1. Explicit `project_path` arg on the tool call.
2. If empty, fall back to `SWARM_KB_PROJECT` environment variable.
3. If still empty, fall back to the **legacy global pool** (backwards-compat during the migration window).

The lifespan caches one `_ProjectState` per resolved `project_path` (lazy-built; closed on shutdown). The shared embedder (~700 MB sentence-transformers model) is built once across the whole server and reused across every per-project `VectorIndex` — only the sqlite-vec database file differs per project.

## How to use

### Single-project session

Set the env var once, every tool routes there:

```bash
export SWARM_KB_PROJECT=/path/to/your/instrument-firmware
swarm-kb serve --transport stdio
```

Or pass `--project` (forthcoming on relevant CLI commands) / pass `project_path` on each MCP call.

### Multi-project orchestration

Don't set the env var; pass `project_path` explicitly on every call. The lifespan caches state per project so switching back-and-forth is cheap.

### Forced legacy mode

Don't set the env var, don't pass `project_path` — tools route to the legacy global pool exactly as before this change. This is the **default behaviour today** so nothing breaks for existing users; will be deprecated in a follow-up release after migration adoption.

## Migrating existing data

If you have a populated `~/.swarm-kb/` from before this layout shipped, run:

```bash
# Dry-run first to see what would happen
swarm-kb migrate-to-per-project --dry-run

# Real run — moves files into projects/<hash>/
swarm-kb migrate-to-per-project

# Optional: keep the legacy global paths in place after copying
swarm-kb migrate-to-per-project --keep-legacy

# For entries that lack a project_path field, bucket them here:
swarm-kb migrate-to-per-project --default-project /path/to/main/project

# After verification, delete leftover legacy paths:
swarm-kb migrate-to-per-project --finalize
```

What the migration does:

1. **Sessions** — for each `<tool>/sessions/<sid>/`, reads `meta.json`'s `project_path` and moves into `projects/<hash>/<tool>/sessions/<sid>/`.
2. **Decisions** — splits `decisions/decisions.jsonl` into per-project files, dedupe-merging by `id`.
3. **Debates** — same for `debates/debates.jsonl`; `debates/active/<dbt>/` follows its `debate.json`'s `project_path`.
4. **Pipelines, code-maps** — moved per their `project_path`.
5. **Vector index** — global `index/kb.db` is dropped (or `.bak`'d with `--keep-legacy`). Re-run `swarm-kb vector-rebuild` per project afterwards.
6. **Project meta.json** — written under each `projects/<hash>/` capturing the original project_path + `migrated_from_legacy: true`.

The migration is **idempotent**: rerunning it skips already-migrated sessions and dedupes JSONL appends. xrefs/ is left untouched (intentionally cross-project).

For entries with no `project_path` field (legacy data from before that field was tracked), the migration buckets them under a synthetic `_legacy_unattributed` project hash — you can later rename that bucket dir if you identify the real owning project.

## After migration

Rebuild the vector index per project (the global one was dropped):

```bash
SWARM_KB_PROJECT=/path/to/project1 swarm-kb vector-rebuild
SWARM_KB_PROJECT=/path/to/project2 swarm-kb vector-rebuild
# ...
```

Or pass `--project` to vector-rebuild once that flag lands (M5 follow-up).

## What stays global

- `config.yaml` — storage root, embedding provider, code-map skip-list.
- `xrefs/` — cross-project linkage. A finding in project A superseded by a decision in project B is a legitimate cross-project xref; this stays at the global root.

## Limitations of this milestone

The shipped milestone is **foundation + migration + lifespan routing**. Specifically NOT yet shipped:

- **Default flip** — empty `project_path` still falls back to legacy global. Until that changes, callers must be explicit about per-project routing for it to take effect. A follow-up release will add a deprecation warning, then require explicit project context.
- **`kb_search_findings` cross-project scope** — the filesystem walk in `kb_search_findings` still iterates the legacy global pool. Per-project session walking + a `--scope=all-projects` cross-project mode is a small follow-up.
- **vector-rebuild `--project` flag** — currently requires `SWARM_KB_PROJECT`; a `--project` flag is convenient and trivial to add.
- **Project listing tool** — `kb_list_projects` to enumerate `projects/*/meta.json` for tooling.

These are tracked for the M5 follow-up.

## Related work

- ADR — [docs/decisions/2026-05-05-per-project-storage.md](../decisions/2026-05-05-per-project-storage.md)
- Vector memory ADR (Phase 1) — `adr-15bde0ae` (stored in swarm-kb decisions store; the JSONL bridge from arch-swarm debate `dbt-852bcd99`)
- `paths.py` — `project_hash_for(project_path)`, `project_root(...)`, `project_tool_sessions_path(...)`
- `config.py` — `SuiteConfig.project_*_path` family
- `server.py` — `_LifespanState.for_project()`, the 53 tool routings
- `migrate_per_project.py` — migration logic
