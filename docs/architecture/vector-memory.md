# Vector memory layer (design draft)

Status: **approved (arch-swarm debate 2026-05-05, adr-15bde0ae)**
Scope: `packages/swarm-kb`
Phase: 1 of 4 (memory → reposition → monitor → self-learning)

## Refinements from debate (winning + soft consensus)

The arch-swarm debate (5 personas: Simplicity, Modularity, Reuse, Scalability, Trade-off Mediator) accepted a tightened v1 with two concessions everyone agreed are cheap and high-value, plus a phased v2/v3 plan.

**v1 (this PR):**
1. Single file `packages/swarm-kb/src/swarm_kb/vector_index.py` (~200 LOC).
2. sqlite + sqlite-vec + `entity_meta` table — single store, transactional. **Source-of-truth is the existing JSONL files** (findings.jsonl, decisions.jsonl, debates.jsonl); sqlite is a *rebuildable materialized index* over them, not a third source. Drop kb.db at any time → `swarm-kb vector-rebuild` reads the JSONL and re-indexes.
3. sentence-transformers `intfloat/multilingual-e5-small` as opt-in extra `[embed-local]` (matches `doc_reader.py` precedent for `[pdf]` / `pymupdf`).
4. **One MCP tool only**: `kb_semantic_search` (vector-only). FTS5 / BM25 hybrid retrieval is **task #4 / v2**.
5. **No** `EmbeddingProvider` / `VectorBackend` abstractions, **no** Letta-tier in code (docs only), **no** per-tool indexes.
6. **Concession 1 — embedder warmup on MCP server startup** (~10 LOC, single thread): imports torch + loads the model in the background so the first finding doesn't pay 1.5–3s cold-start latency on the user's hot path.
7. **Concession 2 — optional `on_write` callback in `FindingWriter` / `DecisionStore` / `DebateStore`**: writers don't import or know about `vector_index`. They take an optional callable that is set at wiring time. This decouples writers from the embedder (they keep `Ca=Ce=0`) without introducing an event bus or new patterns. This is **the** modularity boundary that's expensive to add later — it's worth doing now.
8. Reuse: `swarm_kb._filelock.lock()` for `kb.lock`, `swarm_core.timeutil.now_iso` for timestamps, `swarm_core.ids.generate_id` only if any internal IDs are needed (entity_id reuses finding/decision/proposal IDs).
9. **Kill criterion**: if after 14 days no `kb_semantic_search` calls come from at least 2 distinct tools or personas (not just author/test calls), delete the code.

**v2 (after 2 weeks of usage, gated by measurement):**
- Async indexer behind the same `on_write` callback (if write-latency p99 > 500 ms in real usage). The `on_write` port makes this internal to `vector_index.py` — no writer-contract changes.
- ~~Hybrid retrieval (FTS5 BM25 + vector + entity boost) — task #4.~~ **Shipped in v1** (FTS5 + triggers + `mode='vector'|'bm25'|'hybrid'`).
- Provider abstraction *only if* a real second backend (OpenAI/Voyage/Cohere) has a concrete user requesting it.
- Event bus *only if* monitor-swarm phase 3 needs multi-subscriber semantics that exceed `on_write`.

**v3 (when corpus > 100k entities):**
- Eviction policy (`status=fixed AND created_at < cutoff` first, then oldest).
- ANN parameter tuning (M, efConstruction, efSearch).
- Possibly extract `swarm-vector` as a separate package.

**Open dissent**: Scalability Critic argued async-indexer should be in v1 (cost-asymmetric to retrofit). The `on_write` port mitigates the retrofit risk because the writer-side contract is identical for sync and async implementations behind the port; the "writer-contract change" Scalability worried about is now fully internal to vector_index.py.

## Goal

Add semantic search and retrieval over findings, decisions, and debate proposals with minimal changes to existing writers and zero break of JSONL formats. Foundation for self-learning (phase 4) and monitor-swarm (phase 3).

## Non-goals (phase 1)

- Knowledge graph (Zep-style temporal triples).
- LLM-based entity extraction (Mem0 ADD-mode).
- Custom embedding fine-tuning on MCU/datasheet corpora.
- monitor-swarm trace ingestion (phase 3).

## Decisions

### 1. Backend: sqlite + sqlite-vec + FTS5

One file `~/.swarm-kb/index/kb.db` next to existing JSONL.

- **sqlite** — already Python-batteries-included, WAL for concurrent reads, atomic txn, file-based discipline matches existing project idioms.
- **sqlite-vec** — vec0 virtual tables, ANN search; loadable extension, no C build.
- **FTS5** — built into Python sqlite, BM25 with no new packages.

Alternatives rejected:
- **chromadb** — pulls onnxruntime (~500 MB), overkill at our scale.
- **FAISS / hnswlib** — no metadata, sidecar JSON would create two systems to keep in sync.
- **In-memory numpy** — not durable.

A `VectorBackend` adapter wraps the implementation so sqlite-vec can be swapped for hnswlib later without API churn.

### 2. Embeddings: `intfloat/multilingual-e5-small`

| Property | Value |
|---|---|
| Size | 118 MB |
| Dim | 384 |
| Languages | en + ru + 100 others |
| CPU latency | ~50 ms single, ~5 ms batched |
| License | MIT |

Pluggable via `EmbeddingProvider`:
- `local` (default, sentence-transformers)
- `openai` (text-embedding-3-small if `OPENAI_API_KEY` set)
- `voyage`, `cohere` — later

Configured in `~/.swarm-kb/config.yaml`:
```yaml
embedding:
  provider: local
  model: intfloat/multilingual-e5-small
  cache_dir: ~/.cache/huggingface
```

### 3. What we embed

| Entity | Embedded text | Filterable metadata |
|---|---|---|
| Finding | `title\nactual\nexpected\nsnippet\nsuggestion_action: suggestion_detail` | tool, session_id, expert_role, file, severity, category, status, tags, created_at |
| Decision | `title\ncontext\nrationale\n + consequences` | source_tool, source_session, status, project_path, tags |
| Debate proposal | `topic\nproposal_text` | debate_id, author, status, project_path |
| XRef | not embedded (cheap to scan) | — |

**One global index, not per-tool.** Cross-tool retrieval is the main value (e.g. "show findings and decisions semantically similar to this timing violation").

### 4. Schema

```sql
CREATE VIRTUAL TABLE vec_entities USING vec0(
    entity_id TEXT PRIMARY KEY,
    embedding FLOAT[384]
);

CREATE TABLE entity_meta (
    entity_id     TEXT PRIMARY KEY,
    entity_type   TEXT NOT NULL,  -- finding|decision|debate_proposal
    tool          TEXT,
    session_id    TEXT,
    project_path  TEXT,
    persona       TEXT,
    file          TEXT,
    severity      TEXT,
    status        TEXT,
    tags_json     TEXT,
    text_for_fts  TEXT NOT NULL,
    text_hash     TEXT NOT NULL,  -- skip re-embed on backfill if unchanged
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX idx_meta_type    ON entity_meta(entity_type);
CREATE INDEX idx_meta_tool    ON entity_meta(tool, session_id);
CREATE INDEX idx_meta_status  ON entity_meta(status);

CREATE VIRTUAL TABLE entity_fts USING fts5(
    entity_id UNINDEXED,
    text_for_fts,
    tokenize = 'unicode61 remove_diacritics 2'
);
```

Triggers keep `entity_meta ↔ entity_fts` in sync.

### 5. Hybrid retrieval (Mem0-style)

```
1. Structured filter (SQL WHERE on metadata) → candidate set
2. Parallel:
   a) vector cosine top-K (K=50, on the filtered set)
   b) FTS5 BM25 top-K
3. Merge ranking:
   final = 0.6 · cosine + 0.3 · bm25_norm + 0.1 · entity_boost
   entity_boost: +0.1 if file matches query.file, +0.05 per matching tag.
4. Return top-N (default 10).
```

Pure-vector and pure-BM25 modes via the `mode` parameter.

### 6. API: 3 new MCP tools, 0 broken

```python
kb_semantic_search(
    query: str,
    k: int = 10,
    mode: str = "hybrid",   # hybrid|vector|bm25
    filters: dict = {},      # entity_type, tool, session_id, persona, severity, status, tags, file, project_path
    score_threshold: float = 0.0,
) -> list[SearchResult]      # {entity_id, entity_type, score, text, metadata}

kb_search_findings_semantic(query, ...)    # filters.entity_type = "finding"
kb_search_decisions_semantic(query, ...)   # filters.entity_type = "decision"

kb_vector_rebuild(
    scope: str = "all",      # all|findings|decisions|debates|tool:<name>
    progress_callback = None,
) -> RebuildStats
```

Existing `kb_search_findings`, `kb_get_decisions`, `kb_get_debates` are unchanged. Backwards-compat is total.

### 7. Hooks: how the index stays in sync

Writers expose an optional `on_write` callback (set once at wiring time, not per-call). They never import or reference the vector layer.

```python
# finding_writer.py
class FindingWriter:
    def __init__(self, ..., on_write: Callable | None = None):
        ...
        self._on_write = on_write

    def post(self, finding: dict) -> None:
        with self._lock:
            ...append to JSONL...
            if self._on_write is not None:
                self._on_write(
                    entity_id=finding["id"],
                    entity_type="finding",
                    text=_finding_to_text(finding),
                    metadata=_finding_to_meta(finding),
                )
```

Same shape in `DecisionStore.append()` and `DebateStore.append()` (the latter calls per proposal).

The MCP server wires `on_write = vector_index.upsert` once at startup, *if* the embed-local extra is installed. Otherwise `on_write` stays `None` and writers behave exactly as today.

`vector_index.upsert` is synchronous in v1. Cold-encoder latency is bounded by the warmup thread (the model is hot before the first write). Per-item embedding is ~5–50 ms depending on batch.

**On status update** (`mark_fixed`, `update_status`): update only `entity_meta.status`; the text and embedding stay.

**Concurrency**: single portalocker file `~/.swarm-kb/index/kb.lock` for index writes; sqlite WAL for concurrent reads. Same idiom as existing atomic-rewrite files (`_filelock.lock()`).

### 8. Backfill

CLI:
```
swarm-kb vector-rebuild
swarm-kb vector-rebuild --scope findings
swarm-kb vector-rebuild --scope tool:review
```

Idempotent via `text_hash` — already-indexed entries with the same hash are skipped.

### 9. Three-tier mapping (Letta)

| Letta tier | Swarm Suite | Action |
|---|---|---|
| **core** (always in context) | YAML expert personas | already exists, no change |
| **archival** (vector retrieval) | findings + decisions + debate proposals | this phase |
| **recall** (chronological) | events.jsonl, debate transcripts | unchanged |

The three-tier framing is for documentation; it does not introduce separate code.

## Dependencies

In `packages/swarm-kb/pyproject.toml`:

```toml
dependencies = [
    ...,
    "sqlite-vec>=0.1.5,<0.2",
]

[project.optional-dependencies]
embed-local = [
    "sentence-transformers>=2.7,<5",
]
embed-openai = [
    "openai>=1.0,<2",
]
```

`sentence-transformers` is **opt-in** (it pulls torch ~700 MB). Without an embedding provider, `kb_semantic_search` falls back to `mode=bm25` (FTS5 ships with sqlite, no extra install).

## Tests

- Unit: `VectorIndex.upsert/search/delete`, score merging, filters.
- Integration: writer hooks → search returns the just-written entity.
- Concurrency: two processes write simultaneously, index stays consistent (portalocker).
- Backfill idempotency: rebuild twice → no duplicates.
- Backwards-compat: existing `kb_search_findings` behaves exactly as before.

## Schedule

- Adapter + sqlite-vec setup + schema: 1d
- Embedding adapter (local + openai) + tests: 1d
- Writer hooks (3 points): 2d
- `kb_semantic_search` MCP tool: 1d
- Hybrid ranking (separate PR / task #4): 1d
- Backfill CLI + tests: 1d
- Docs + example: 1d

~6–7 days to first PR; hybrid retrieval after.

## Open questions — resolved by debate

1. Optional vs required dep for `sentence-transformers`? → **optional `[embed-local]` extra**. Without it, `kb_semantic_search` raises a clear "embedding provider not configured" error. (Unanimous.)
2. One global index vs per-tool? → **one global**. Cross-tool retrieval is the main value. (Unanimous.)
3. sqlite-vec vs hnswlib? → **sqlite-vec for v1**. Swap behind in-module functions is one day's work if it proves flaky.
4. Embed-on-write (sync) vs background queue? → **sync v1, async behind `on_write` port in v2 if write-latency p99 > 500 ms in real usage**. The port makes this swap internal.
5. Schema future-proofing for monitor-swarm phase 3? → `entity_type` is a string column; new types (`trace_event`, `timing_violation`) add without migration. No pre-emptive schema work needed.
