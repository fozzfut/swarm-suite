# Session storage

All persistent state lives under `~/.swarm-kb/`.

```
~/.swarm-kb/
|-- sessions/
|   |-- spec/<spec-YYYY-MM-DD-NNN>/
|   |-- arch/<arch-YYYY-MM-DD-NNN>/
|   |-- review/<sess-YYYY-MM-DD-NNN>/
|   |-- fix/<fix-YYYY-MM-DD-NNN>/
|   |-- doc/<doc-YYYY-MM-DD-NNN>/
|   '-- (each session dir contains:)
|       |-- meta.json              <- atomic write (tempfile + os.replace)
|       |-- findings.jsonl         <- append-only
|       |-- claims.json            <- atomic write (read-modify-write)
|       |-- reactions.jsonl        <- append-only
|       |-- events.jsonl           <- append-only
|       |-- messages.jsonl         <- append-only
|       |-- phases.json            <- atomic write
|       |-- report.md / .json / .sarif (auto-generated on end_session)
|       '-- transcript.md          <- arch / spec only
|-- decisions/                     <- ADRs (cross-session)
|-- debates/active/                <- live debates
|-- pipelines/                     <- per-project pipeline state
|-- code-maps/<project-hash>/      <- AST analysis cache
|-- xrefs.jsonl                    <- finding -> fix -> verification chain
|-- quality_gate.json              <- per-project thresholds
'-- logs/<tool>.log*               <- rotating daily, 30-day retention
```

## File semantics

| File type | Write mode | Locking | Notes |
|-----------|-----------|---------|-------|
| `meta.json`, `claims.json`, `phases.json` | atomic replace | per-process `RLock` + tempfile | readers tolerate `FileNotFoundError` mid-replace |
| `*.jsonl` | append-only | OS-level (`O_APPEND` is atomic for lines under PIPE_BUF) | one JSON per line, no commas |
| `report.md/.json/.sarif` | atomic replace | per-process `RLock` | regenerated on `end_session` |
| `transcript.md` | atomic replace | per-process `RLock` | arch/spec only |
| `xrefs.jsonl`, `quality_gate.json` | atomic replace OR append | swarm-kb internal | cross-session; use the high-level API |

## Session ID format

`<prefix>-YYYY-MM-DD-NNN` where prefix is the tool short name
(`sess`, `fix`, `arch`, `doc`, `spec`). NNN is a daily sequence
starting at 001. UUID fallback (`<prefix>-YYYY-MM-DD-<6 hex>`) only
on race collision.

UUID-based session IDs MUST NOT be exposed to users as primary IDs.

## Schema versioning

Every persisted record has `schema_version: int` at the top level.
Readers MUST tolerate `schema_version` >= their own: log a warning,
read what they understand, ignore unknown keys. NEVER fail the read.

The current `schema_version` for every record type is 1. When a
breaking change is needed:

1. Bump the version in the writer.
2. Add a reader branch in the corresponding `*_store.py` for the new
   version.
3. Write a migration in `swarm_kb.compat` that converts old to new
   on first read.
4. Document the change in `docs/decisions/`.

## Atomic write helper

Use `swarm_core.io.atomic_write_text(path, content)`. Manual
`open(path, "w").write(...)` for files other processes read =
data corruption risk; the keeper / review-swarm flag this.

## Append-only invariant

JSONL files MUST never be edited in place except via the
`mark_fixed`-style read-modify-atomic-replace pattern in
`swarm_kb.finding_reader.FindingReader.mark_fixed`. The pattern:

1. Acquire process lock.
2. Read all lines.
3. Modify the target line in memory.
4. Write to a tempfile.
5. `os.replace(tempfile, original)`.

Skipping step 4-5 in favor of `seek + truncate + write` corrupts
the file if the process is killed mid-write.
