"""Vector memory layer over swarm-kb findings and decisions.

v1: sqlite + sqlite-vec virtual table for embeddings, opt-in
sentence-transformers for embedding generation.

Source-of-truth stays in the existing JSONL files. The sqlite db
``kb.db`` is a *materialized index* that can be rebuilt at any
time from JSONL via :meth:`VectorIndex.rebuild_from_jsonl`.

See ``docs/architecture/vector-memory.md`` (adr-15bde0ae).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import struct
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from swarm_core.timeutil import now_iso

from ._filelock import cross_process_lock
from .config import SuiteConfig, TOOL_NAMES

_log = logging.getLogger("swarm_kb.vector_index")

EMBEDDING_DIM = 384  # multilingual-e5-small
DEFAULT_MODEL = "intfloat/multilingual-e5-small"

# v1 indexes findings and decisions only. Debate proposals are
# revisited in v2 alongside self-learning.
ENTITY_FINDING = "finding"
ENTITY_DECISION = "decision"

_SCHEMA_SQL = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS vec_entities USING vec0(
    embedding FLOAT[{EMBEDDING_DIM}]
);

CREATE TABLE IF NOT EXISTS entity_meta (
    entity_id      TEXT PRIMARY KEY,
    rowid_in_vec   INTEGER NOT NULL UNIQUE,
    entity_type    TEXT NOT NULL,
    tool           TEXT,
    session_id     TEXT,
    project_path   TEXT,
    persona        TEXT,
    file           TEXT,
    severity       TEXT,
    status         TEXT,
    tags_json      TEXT,
    metadata_json  TEXT,
    text_for_search TEXT NOT NULL,
    text_hash      TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meta_type   ON entity_meta(entity_type);
CREATE INDEX IF NOT EXISTS idx_meta_tool   ON entity_meta(tool, session_id);
CREATE INDEX IF NOT EXISTS idx_meta_status ON entity_meta(status);
CREATE INDEX IF NOT EXISTS idx_meta_file   ON entity_meta(file);

-- FTS5 BM25 index over entity_meta.text_for_search (task #4 hybrid retrieval).
-- Kept in sync via triggers below; source-of-truth is entity_meta.
CREATE VIRTUAL TABLE IF NOT EXISTS entity_fts USING fts5(
    entity_id UNINDEXED,
    text_for_search,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS entity_meta_ai
AFTER INSERT ON entity_meta
BEGIN
    INSERT INTO entity_fts(entity_id, text_for_search)
    VALUES (NEW.entity_id, NEW.text_for_search);
END;

CREATE TRIGGER IF NOT EXISTS entity_meta_au
AFTER UPDATE OF text_for_search ON entity_meta
BEGIN
    UPDATE entity_fts SET text_for_search = NEW.text_for_search
     WHERE entity_id = NEW.entity_id;
END;

CREATE TRIGGER IF NOT EXISTS entity_meta_ad
AFTER DELETE ON entity_meta
BEGIN
    DELETE FROM entity_fts WHERE entity_id = OLD.entity_id;
END;
"""


# ─── Embedder ──────────────────────────────────────────────────────────────


class Embedder:
    """Embedder protocol. Use :class:`LocalEmbedder` for the default."""

    dim: int

    def encode(self, text: str, *, is_query: bool = False) -> list[float]:
        raise NotImplementedError

    def encode_batch(
        self, texts: list[str], *, is_query: bool = False
    ) -> list[list[float]]:
        raise NotImplementedError

    def warmup(self) -> None:
        """Eagerly load any heavy resources."""
        raise NotImplementedError


class LocalEmbedder(Embedder):
    """sentence-transformers backed embedder. Lazy-loads the model."""

    dim = EMBEDDING_DIM

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model: Any = None
        self._lock = threading.Lock()

    def _model_or_load(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer
                    _log.info("Loading embedding model %s", self._model_name)
                    self._model = SentenceTransformer(self._model_name)
        return self._model

    def warmup(self) -> None:
        try:
            self._model_or_load()
        except Exception as exc:
            _log.warning("Embedder warmup failed: %s", exc)

    def encode(self, text: str, *, is_query: bool = False) -> list[float]:
        prefix = "query: " if is_query else "passage: "
        model = self._model_or_load()
        vec = model.encode(prefix + text, normalize_embeddings=True)
        return vec.tolist() if hasattr(vec, "tolist") else list(vec)

    def encode_batch(
        self, texts: list[str], *, is_query: bool = False
    ) -> list[list[float]]:
        if not texts:
            return []
        prefix = "query: " if is_query else "passage: "
        model = self._model_or_load()
        prefixed = [prefix + t for t in texts]
        arr = model.encode(prefixed, normalize_embeddings=True, batch_size=32)
        return [list(v) for v in arr]


def make_embedder(config_section: dict | None) -> Embedder | None:
    """Construct an embedder from config, or return None.

    Returns None when no provider is configured OR when the provider's
    optional dependency is missing (graceful fallback per doc_reader's
    pattern). The MCP tool ``kb_semantic_search`` will return an
    informative error in that case.
    """
    if not config_section:
        return None
    provider = (config_section.get("provider") or "").strip().lower()
    if not provider:
        return None
    if provider == "local":
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            _log.warning(
                "Embedding provider 'local' requested but sentence-transformers "
                "is not installed. Install with: pip install swarm-kb[embed-local]"
            )
            return None
        return LocalEmbedder(model_name=config_section.get("model") or DEFAULT_MODEL)
    raise ValueError(f"Unknown embedding provider: {provider!r}")


def start_warmup_thread(embedder: Embedder | None) -> threading.Thread | None:
    """Eagerly load the embedder model in a background thread."""
    if embedder is None:
        return None
    t = threading.Thread(
        target=embedder.warmup,
        name="vector-index-warmup",
        daemon=True,
    )
    t.start()
    return t


# ─── Vector helpers ─────────────────────────────────────────────────────────


def _vec_blob(values: list[float]) -> bytes:
    """Pack a float vector into the binary blob sqlite-vec expects."""
    if len(values) != EMBEDDING_DIM:
        raise ValueError(
            f"Expected {EMBEDDING_DIM}-dim vector, got {len(values)}"
        )
    return struct.pack(f"{EMBEDDING_DIM}f", *values)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_meta(meta_json: str | None) -> dict:
    """Parse JSON metadata; return {} on any failure."""
    if not meta_json:
        return {}
    try:
        out = json.loads(meta_json)
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


def _fts_safe(query: str) -> str:
    """Escape a user query for FTS5 MATCH so punctuation doesn't break parsing.

    FTS5 syntax treats characters like ``" : ( ) -`` specially. The simplest
    robust strategy: split into tokens, drop empty / single-char tokens, wrap
    each in double quotes, and join with spaces (implicit AND in FTS5).
    """
    tokens = [t for t in (query or "").split() if t]
    quoted = []
    for tok in tokens:
        # Strip embedded double quotes (FTS5 string literal terminator)
        clean = tok.replace('"', "")
        if not clean or len(clean) < 2:
            continue
        quoted.append(f'"{clean}"')
    return " ".join(quoted) or '""'


# ─── Entity → text/metadata ─────────────────────────────────────────────────


def finding_to_text(f: dict) -> str:
    parts = [
        f.get("title", ""),
        f.get("actual", ""),
        f.get("expected", ""),
        (f.get("snippet", "") or "")[:500],
        f.get("suggestion_action", ""),
        f.get("suggestion_detail", ""),
    ]
    return "\n".join(p for p in parts if p).strip() or f.get("id", "")


def finding_to_meta(f: dict, tool: str, session_id: str) -> dict:
    return {
        "tool": tool,
        "session_id": session_id,
        "project_path": f.get("project_path", ""),
        "persona": f.get("expert_role", ""),
        "file": f.get("file", ""),
        "severity": f.get("severity", ""),
        "status": f.get("status", "open"),
        "tags": list(f.get("tags") or []),
    }


def decision_to_text(d: dict) -> str:
    consequences = d.get("consequences") or []
    parts = [
        d.get("title", ""),
        d.get("context", ""),
        d.get("rationale", ""),
        "\n".join(c for c in consequences if c),
    ]
    return "\n".join(p for p in parts if p).strip() or d.get("id", "")


def decision_to_meta(d: dict) -> dict:
    return {
        "tool": d.get("source_tool", ""),
        "session_id": d.get("source_session", ""),
        "project_path": d.get("project_path", ""),
        "persona": "",
        "file": "",
        "severity": "",
        "status": d.get("status", "proposed"),
        "tags": list(d.get("tags") or []),
    }


# ─── VectorIndex ────────────────────────────────────────────────────────────


@dataclass
class SearchResult:
    entity_id: str
    entity_type: str
    score: float  # 0..1, higher is better (cosine similarity)
    text: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "score": self.score,
            "text": self.text,
            "metadata": self.metadata,
        }


@dataclass
class RebuildStats:
    indexed: int = 0
    skipped: int = 0
    errors: int = 0
    by_type: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "indexed": self.indexed,
            "skipped": self.skipped,
            "errors": self.errors,
            "by_type": dict(self.by_type),
        }


class VectorIndex:
    """SQLite + sqlite-vec backed semantic index over swarm-kb entities.

    Uses the existing ``_filelock.cross_process_lock`` discipline for
    cross-process safety on writes; sqlite WAL mode enables concurrent
    readers.

    When ``embedder`` is None, ``upsert``/``search`` raise; this lets
    the caller branch on availability without try/except. ``count``,
    ``delete``, and ``update_metadata`` work without an embedder
    (they don't need to compute vectors).
    """

    def __init__(
        self,
        db_path: Path,
        embedder: Embedder | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._lock_path = self._db_path.with_suffix(".lock")
        self._embedder = embedder
        self._tlock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # -- connection lifecycle ------------------------------------------------

    def _conn_or_open(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                isolation_level=None,  # autocommit; we manage txn explicitly
            )
            try:
                conn.enable_load_extension(True)
            except sqlite3.NotSupportedError as exc:  # pragma: no cover
                conn.close()
                raise RuntimeError(
                    "This Python build's sqlite3 has loadable extensions disabled "
                    "(macOS system Python is the usual culprit). Use a Homebrew or "
                    "pyenv-built Python that ships with --enable-load-extension."
                ) from exc
            try:
                import sqlite_vec
                sqlite_vec.load(conn)
            finally:
                conn.enable_load_extension(False)
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.executescript(_SCHEMA_SQL)
            self._conn = conn
        return self._conn

    def close(self) -> None:
        with self._tlock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # -- write path ----------------------------------------------------------

    def upsert(
        self,
        *,
        entity_id: str,
        entity_type: str,
        text: str,
        metadata: dict,
    ) -> None:
        """Embed ``text`` and insert/update the index entry.

        If the text hasn't changed since the last call (compared by
        SHA-256), only metadata is updated; the embedding stays.
        """
        if not entity_id:
            raise ValueError("entity_id is required")
        if self._embedder is None:
            raise RuntimeError(
                "Embedder not configured. Install with: "
                "pip install swarm-kb[embed-local]"
            )

        text = text or ""
        text_hash = _text_hash(text)

        with self._tlock, cross_process_lock(self._lock_path):
            conn = self._conn_or_open()
            cur = conn.execute(
                "SELECT rowid_in_vec, text_hash FROM entity_meta WHERE entity_id = ?",
                (entity_id,),
            )
            row = cur.fetchone()
            ts = now_iso()
            tags_json = json.dumps(list(metadata.get("tags") or []))
            full_meta_json = json.dumps(metadata)

            if row:
                rowid_in_vec, existing_hash = row
                if existing_hash != text_hash:
                    embedding = self._embedder.encode(text)
                    conn.execute(
                        "UPDATE vec_entities SET embedding = ? WHERE rowid = ?",
                        (_vec_blob(embedding), rowid_in_vec),
                    )
                conn.execute(
                    """
                    UPDATE entity_meta
                       SET entity_type = ?,
                           tool = ?,
                           session_id = ?,
                           project_path = ?,
                           persona = ?,
                           file = ?,
                           severity = ?,
                           status = ?,
                           tags_json = ?,
                           metadata_json = ?,
                           text_for_search = ?,
                           text_hash = ?,
                           updated_at = ?
                     WHERE entity_id = ?
                    """,
                    (
                        entity_type,
                        metadata.get("tool", ""),
                        metadata.get("session_id", ""),
                        metadata.get("project_path", ""),
                        metadata.get("persona", ""),
                        metadata.get("file", ""),
                        metadata.get("severity", ""),
                        metadata.get("status", ""),
                        tags_json,
                        full_meta_json,
                        text,
                        text_hash,
                        ts,
                        entity_id,
                    ),
                )
            else:
                embedding = self._embedder.encode(text)
                cur = conn.execute(
                    "INSERT INTO vec_entities(embedding) VALUES (?)",
                    (_vec_blob(embedding),),
                )
                rowid_in_vec = cur.lastrowid
                conn.execute(
                    """
                    INSERT INTO entity_meta(
                        entity_id, rowid_in_vec, entity_type, tool,
                        session_id, project_path, persona, file, severity,
                        status, tags_json, metadata_json, text_for_search,
                        text_hash, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity_id,
                        rowid_in_vec,
                        entity_type,
                        metadata.get("tool", ""),
                        metadata.get("session_id", ""),
                        metadata.get("project_path", ""),
                        metadata.get("persona", ""),
                        metadata.get("file", ""),
                        metadata.get("severity", ""),
                        metadata.get("status", ""),
                        tags_json,
                        full_meta_json,
                        text,
                        text_hash,
                        ts,
                        ts,
                    ),
                )

    def update_metadata(
        self, entity_id: str, **fields: Any
    ) -> bool:
        """Patch metadata fields without re-embedding. Returns True if found.

        Accepts: tool, session_id, project_path, persona, file, severity,
        status, tags (list), and metadata_json (full replace).
        """
        allowed = {
            "tool", "session_id", "project_path", "persona", "file",
            "severity", "status",
        }
        sets: list[str] = []
        params: list[Any] = []
        for k, v in fields.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                params.append(v)
            elif k == "tags":
                sets.append("tags_json = ?")
                params.append(json.dumps(list(v or [])))
            elif k == "metadata_json":
                sets.append("metadata_json = ?")
                params.append(v)
        if not sets:
            return False
        sets.append("updated_at = ?")
        params.append(now_iso())
        params.append(entity_id)

        with self._tlock, cross_process_lock(self._lock_path):
            conn = self._conn_or_open()
            cur = conn.execute(
                f"UPDATE entity_meta SET {', '.join(sets)} WHERE entity_id = ?",
                params,
            )
            return cur.rowcount > 0

    def delete(self, entity_id: str) -> bool:
        with self._tlock, cross_process_lock(self._lock_path):
            conn = self._conn_or_open()
            cur = conn.execute(
                "SELECT rowid_in_vec FROM entity_meta WHERE entity_id = ?",
                (entity_id,),
            )
            row = cur.fetchone()
            if row is None:
                return False
            rowid = row[0]
            conn.execute("DELETE FROM vec_entities WHERE rowid = ?", (rowid,))
            conn.execute("DELETE FROM entity_meta WHERE entity_id = ?", (entity_id,))
            return True

    # -- search --------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        k: int = 10,
        mode: str = "vector",
        filters: dict | None = None,
        score_threshold: float = 0.0,
    ) -> list[SearchResult]:
        """Semantic / lexical / hybrid search.

        ``mode`` is one of:
        - ``vector`` (default) — cosine similarity via sqlite-vec; needs embedder.
        - ``bm25`` — FTS5 BM25 over text_for_search; works without an embedder.
        - ``hybrid`` — merged ranking 0.6·vec + 0.3·bm25 + 0.1·entity_boost.

        ``filters`` supports exact-match on entity_type, tool, session_id,
        persona, file, severity, status, project_path, plus ``tags`` (list,
        treated as 'must contain at least one').

        Score is in [0, 1]; higher is better. ``score_threshold`` filters
        out weak matches.
        """
        if not query.strip():
            return []
        mode = (mode or "vector").lower()
        if mode not in ("vector", "bm25", "hybrid"):
            raise ValueError(f"Unknown mode: {mode!r}")
        if mode in ("vector", "hybrid") and self._embedder is None:
            raise RuntimeError(
                "Embedder not configured (mode=%s requires it). Install with: "
                "pip install swarm-kb[embed-local], "
                "or use mode='bm25' for lexical-only search." % mode
            )

        filters = filters or {}
        if mode == "bm25":
            return self._search_bm25(query, k, filters, score_threshold)
        if mode == "hybrid":
            return self._search_hybrid(query, k, filters, score_threshold)
        return self._search_vector(query, k, filters, score_threshold)

    # -- search backends -----------------------------------------------------

    @staticmethod
    def _build_filter_sql(filters: dict) -> tuple[str, list[Any]]:
        where: list[str] = []
        params: list[Any] = []
        for col in ("entity_type", "tool", "session_id", "persona", "file",
                    "severity", "status", "project_path"):
            v = filters.get(col)
            if v:
                where.append(f"em.{col} = ?")
                params.append(v)
        tags = filters.get("tags") or []
        if tags:
            like_clauses = []
            for t in tags:
                like_clauses.append("em.tags_json LIKE ?")
                params.append(f'%"{t}"%')
            where.append("(" + " OR ".join(like_clauses) + ")")
        where_sql = ("AND " + " AND ".join(where)) if where else ""
        return where_sql, params

    def _search_vector(
        self,
        query: str,
        k: int,
        filters: dict,
        score_threshold: float,
    ) -> list[SearchResult]:
        embedding = self._embedder.encode(query, is_query=True)
        # Safety multiplier so post-filter still has enough hits.
        candidate_k = max(k * 20, 50)
        where_sql, where_params = self._build_filter_sql(filters)

        sql = f"""
            SELECT em.entity_id, em.entity_type, em.text_for_search,
                   em.metadata_json, v.distance
              FROM vec_entities v
              JOIN entity_meta em ON em.rowid_in_vec = v.rowid
             WHERE v.embedding MATCH ?
               AND k = ?
               {where_sql}
             ORDER BY v.distance
             LIMIT ?
        """
        params = [_vec_blob(embedding), candidate_k, *where_params, k]

        with self._tlock:
            conn = self._conn_or_open()
            rows = conn.execute(sql, params).fetchall()

        out: list[SearchResult] = []
        for entity_id, entity_type, text, meta_json, distance in rows:
            # sqlite-vec returns cosine *distance* (0 = identical, 2 = opposite).
            score = max(0.0, 1.0 - float(distance) / 2.0)
            if score < score_threshold:
                continue
            out.append(SearchResult(
                entity_id=entity_id,
                entity_type=entity_type,
                score=score,
                text=text,
                metadata=_safe_meta(meta_json),
            ))
        return out

    def _search_bm25(
        self,
        query: str,
        k: int,
        filters: dict,
        score_threshold: float,
    ) -> list[SearchResult]:
        # FTS5 returns rank where lower is better (negative numbers, lower = stronger).
        # Convert to a 0..1 similarity by inverting and normalising.
        where_sql, where_params = self._build_filter_sql(filters)

        sql = f"""
            SELECT em.entity_id, em.entity_type, em.text_for_search,
                   em.metadata_json, bm25(entity_fts) AS rank
              FROM entity_fts
              JOIN entity_meta em ON em.entity_id = entity_fts.entity_id
             WHERE entity_fts MATCH ?
               {where_sql}
             ORDER BY rank
             LIMIT ?
        """
        # FTS5 MATCH expects an FTS query expression. Quote the user query to
        # treat it as a phrase / safe token sequence (avoid syntax errors on
        # punctuation in the user's text). For multi-word queries this matches
        # any document containing those tokens anywhere.
        fts_query = _fts_safe(query)
        params = [fts_query, *where_params, max(k * 5, 25)]

        with self._tlock:
            conn = self._conn_or_open()
            rows = conn.execute(sql, params).fetchall()

        if not rows:
            return []

        # bm25 in sqlite-fts5 returns negative numbers (more negative = better).
        # Normalise to 0..1 using the best (most-negative) score in the result set.
        best = min(r[4] for r in rows) or -1.0
        out: list[SearchResult] = []
        for entity_id, entity_type, text, meta_json, rank in rows[:k]:
            # Map rank in [best, 0] to similarity in [1, 0]
            sim = float(rank) / float(best) if best != 0 else 0.0
            sim = max(0.0, min(1.0, sim))
            if sim < score_threshold:
                continue
            out.append(SearchResult(
                entity_id=entity_id,
                entity_type=entity_type,
                score=sim,
                text=text,
                metadata=_safe_meta(meta_json),
            ))
        return out

    def _search_hybrid(
        self,
        query: str,
        k: int,
        filters: dict,
        score_threshold: float,
    ) -> list[SearchResult]:
        # Pull wider candidate sets from each backend, merge, re-rank.
        wider = max(k * 3, 30)
        vec_hits = self._search_vector(query, wider, filters, 0.0)
        bm25_hits = self._search_bm25(query, wider, filters, 0.0)

        merged: dict[str, dict] = {}
        for r in vec_hits:
            merged[r.entity_id] = {
                "result": r, "vec": r.score, "bm25": 0.0,
            }
        for r in bm25_hits:
            slot = merged.setdefault(r.entity_id, {
                "result": r, "vec": 0.0, "bm25": 0.0,
            })
            slot["bm25"] = r.score

        query_file = (filters.get("file") or "").strip()
        query_tags = set(filters.get("tags") or [])

        out: list[SearchResult] = []
        for entity_id, slot in merged.items():
            r: SearchResult = slot["result"]
            meta = r.metadata or {}
            boost = 0.0
            if query_file and meta.get("file") == query_file:
                boost += 1.0
            result_tags = set(meta.get("tags") or [])
            overlap = len(query_tags & result_tags)
            if overlap:
                boost += min(overlap / max(len(query_tags), 1), 1.0)
            boost = min(boost, 1.0)

            final = 0.6 * slot["vec"] + 0.3 * slot["bm25"] + 0.1 * boost
            if final < score_threshold:
                continue
            r.score = final
            out.append(r)

        out.sort(key=lambda r: r.score, reverse=True)
        return out[:k]

    # -- introspection -------------------------------------------------------

    def count(self, entity_type: str | None = None) -> int:
        with self._tlock:
            conn = self._conn_or_open()
            if entity_type:
                cur = conn.execute(
                    "SELECT COUNT(*) FROM entity_meta WHERE entity_type = ?",
                    (entity_type,),
                )
            else:
                cur = conn.execute("SELECT COUNT(*) FROM entity_meta")
            return int(cur.fetchone()[0])

    # -- backfill ------------------------------------------------------------

    def rebuild_from_jsonl(
        self,
        config: SuiteConfig,
        scope: str = "all",
    ) -> RebuildStats:
        """Re-index from existing JSONL source-of-truth files.

        ``scope`` is one of: ``all``, ``findings``, ``decisions``, or
        ``tool:<name>`` to restrict findings to one tool's sessions.
        Idempotent: entities whose text_hash matches the indexed
        version are skipped.
        """
        stats = RebuildStats()
        if self._embedder is None:
            raise RuntimeError(
                "Embedder not configured. Install with: "
                "pip install swarm-kb[embed-local]"
            )

        do_findings = scope in ("all", "findings") or scope.startswith("tool:")
        do_decisions = scope in ("all", "decisions")
        tool_filter: Optional[str] = None
        if scope.startswith("tool:"):
            tool_filter = scope.split(":", 1)[1]

        if do_findings:
            tools = (tool_filter,) if tool_filter else TOOL_NAMES
            for tool in tools:
                sessions_dir = config.tool_sessions_path(tool)
                if not sessions_dir.exists():
                    continue
                for entry in sorted(sessions_dir.iterdir()):
                    if not entry.is_dir():
                        continue
                    findings_path = entry / "findings.jsonl"
                    if not findings_path.exists():
                        continue
                    self._reindex_findings_file(
                        findings_path, tool, entry.name, stats,
                    )

        if do_decisions:
            decisions_path = config.decisions_path / "decisions.jsonl"
            if decisions_path.exists():
                self._reindex_decisions_file(decisions_path, stats)

        return stats

    def _reindex_findings_file(
        self,
        path: Path,
        tool: str,
        session_id: str,
        stats: RebuildStats,
    ) -> None:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            _log.warning("Cannot read %s: %s", path, exc)
            stats.errors += 1
            return
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                f = json.loads(line)
            except json.JSONDecodeError:
                stats.errors += 1
                continue
            if not f.get("id"):
                stats.skipped += 1
                continue
            try:
                self.upsert(
                    entity_id=f["id"],
                    entity_type=ENTITY_FINDING,
                    text=finding_to_text(f),
                    metadata=finding_to_meta(f, tool, session_id),
                )
                stats.indexed += 1
                stats.by_type[ENTITY_FINDING] = stats.by_type.get(ENTITY_FINDING, 0) + 1
            except Exception as exc:
                _log.warning("Failed to index finding %s: %s", f.get("id"), exc)
                stats.errors += 1

    def _reindex_decisions_file(self, path: Path, stats: RebuildStats) -> None:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            _log.warning("Cannot read %s: %s", path, exc)
            stats.errors += 1
            return
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                stats.errors += 1
                continue
            if not d.get("id"):
                stats.skipped += 1
                continue
            try:
                self.upsert(
                    entity_id=d["id"],
                    entity_type=ENTITY_DECISION,
                    text=decision_to_text(d),
                    metadata=decision_to_meta(d),
                )
                stats.indexed += 1
                stats.by_type[ENTITY_DECISION] = stats.by_type.get(ENTITY_DECISION, 0) + 1
            except Exception as exc:
                _log.warning("Failed to index decision %s: %s", d.get("id"), exc)
                stats.errors += 1


# ─── on_write callback factories ────────────────────────────────────────────


def make_finding_indexer(
    vector_index: VectorIndex,
    tool: str,
    session_id: str,
) -> Callable[[dict], None]:
    """Return an ``on_write`` callable suitable for FindingWriter.

    The callable swallows exceptions and logs them — JSONL is the
    durable source of truth, the index is best-effort.
    """
    def _on_write(finding: dict) -> None:
        try:
            vector_index.upsert(
                entity_id=finding["id"],
                entity_type=ENTITY_FINDING,
                text=finding_to_text(finding),
                metadata=finding_to_meta(finding, tool, session_id),
            )
        except Exception as exc:
            _log.warning(
                "Vector index hook failed for finding %s: %s",
                finding.get("id"), exc,
            )
    return _on_write


def make_decision_indexer(
    vector_index: VectorIndex,
) -> Callable[[dict], None]:
    """Return an ``on_write`` callable suitable for DecisionStore."""
    def _on_write(decision: dict) -> None:
        try:
            vector_index.upsert(
                entity_id=decision["id"],
                entity_type=ENTITY_DECISION,
                text=decision_to_text(decision),
                metadata=decision_to_meta(decision),
            )
        except Exception as exc:
            _log.warning(
                "Vector index hook failed for decision %s: %s",
                decision.get("id"), exc,
            )
    return _on_write
