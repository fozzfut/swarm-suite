"""Unit tests for vector_index + on_write integration in writers.

These use a deterministic MockEmbedder so torch/sentence-transformers
are not required. Tests that touch sqlite-vec are gated on its
availability (it's a hard dep, but allow graceful skip).

Real-embedder integration tests belong in a separate file (not yet
written) and require ``pip install swarm-kb[embed-local]``.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest

from swarm_kb.config import SuiteConfig
from swarm_kb.decision_store import DecisionStore
from swarm_kb.finding_writer import FindingWriter

try:
    import sqlite_vec  # noqa: F401
    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    _SQLITE_VEC_AVAILABLE = False

needs_sqlite_vec = pytest.mark.skipif(
    not _SQLITE_VEC_AVAILABLE,
    reason="sqlite-vec not installed",
)


# ─── MockEmbedder ───────────────────────────────────────────────────────────


def _import_vector():
    """Defer import of vector_index until tests run (so missing sqlite-vec
    fails the marker, not module-level)."""
    from swarm_kb import vector_index
    return vector_index


class MockEmbedder:
    """Deterministic, pure-Python embedder. Same text -> same vector."""

    def __init__(self) -> None:
        self.encode_calls = 0
        from swarm_kb.vector_index import EMBEDDING_DIM
        self.dim = EMBEDDING_DIM

    def warmup(self) -> None:
        pass

    def encode(self, text: str, *, is_query: bool = False) -> list[float]:
        self.encode_calls += 1
        seed = int.from_bytes(hashlib.md5(text.encode("utf-8")).digest()[:4], "big")
        rng = random.Random(seed)
        vec = [rng.uniform(-1.0, 1.0) for _ in range(self.dim)]
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [x / norm for x in vec]

    def encode_batch(self, texts, *, is_query: bool = False):
        return [self.encode(t, is_query=is_query) for t in texts]


# ─── VectorIndex unit tests ────────────────────────────────────────────────


@needs_sqlite_vec
def test_upsert_and_count(tmp_path: Path) -> None:
    vi = _import_vector()
    idx = vi.VectorIndex(tmp_path / "kb.db", embedder=MockEmbedder())
    try:
        idx.upsert(
            entity_id="f-001",
            entity_type="finding",
            text="SQL injection in login query",
            metadata={"tool": "review", "severity": "high", "status": "open"},
        )
        idx.upsert(
            entity_id="d-001",
            entity_type="decision",
            text="Switch to parameterized queries",
            metadata={"status": "accepted"},
        )
        assert idx.count() == 2
        assert idx.count(entity_type="finding") == 1
        assert idx.count(entity_type="decision") == 1
        assert idx.count(entity_type="missing") == 0
    finally:
        idx.close()


@needs_sqlite_vec
def test_upsert_skips_reembed_on_same_text(tmp_path: Path) -> None:
    vi = _import_vector()
    e = MockEmbedder()
    idx = vi.VectorIndex(tmp_path / "kb.db", embedder=e)
    try:
        idx.upsert(
            entity_id="x", entity_type="finding",
            text="bug A", metadata={"status": "open"},
        )
        first = e.encode_calls
        assert first == 1

        # Same text, different metadata -> no re-embed
        idx.upsert(
            entity_id="x", entity_type="finding",
            text="bug A", metadata={"status": "fixed"},
        )
        assert e.encode_calls == first

        # Changed text -> re-embed
        idx.upsert(
            entity_id="x", entity_type="finding",
            text="bug B", metadata={"status": "fixed"},
        )
        assert e.encode_calls == first + 1
    finally:
        idx.close()


@needs_sqlite_vec
def test_update_metadata_does_not_reembed(tmp_path: Path) -> None:
    vi = _import_vector()
    e = MockEmbedder()
    idx = vi.VectorIndex(tmp_path / "kb.db", embedder=e)
    try:
        idx.upsert(
            entity_id="d", entity_type="decision",
            text="we picked option X",
            metadata={"status": "proposed"},
        )
        before = e.encode_calls
        ok = idx.update_metadata("d", status="accepted", tags=["arch", "ship"])
        assert ok is True
        assert e.encode_calls == before
        # Missing entity
        assert idx.update_metadata("nope", status="x") is False
    finally:
        idx.close()


@needs_sqlite_vec
def test_delete(tmp_path: Path) -> None:
    vi = _import_vector()
    idx = vi.VectorIndex(tmp_path / "kb.db", embedder=MockEmbedder())
    try:
        idx.upsert(entity_id="a", entity_type="finding", text="x", metadata={})
        idx.upsert(entity_id="b", entity_type="finding", text="y", metadata={})
        assert idx.count() == 2
        assert idx.delete("a") is True
        assert idx.delete("a") is False
        assert idx.count() == 1
    finally:
        idx.close()


@needs_sqlite_vec
def test_search_filter_by_entity_type(tmp_path: Path) -> None:
    vi = _import_vector()
    idx = vi.VectorIndex(tmp_path / "kb.db", embedder=MockEmbedder())
    try:
        idx.upsert(
            entity_id="f-1", entity_type="finding",
            text="SPI clock exceeds datasheet max",
            metadata={"tool": "review", "file": "src/spi.c", "severity": "high"},
        )
        idx.upsert(
            entity_id="d-1", entity_type="decision",
            text="Use external crystal for SPI bus",
            metadata={"status": "accepted"},
        )

        only_findings = idx.search("SPI", filters={"entity_type": "finding"})
        assert all(r.entity_type == "finding" for r in only_findings)
        only_decisions = idx.search("SPI", filters={"entity_type": "decision"})
        assert all(r.entity_type == "decision" for r in only_decisions)
    finally:
        idx.close()


@needs_sqlite_vec
def test_search_filter_by_tag(tmp_path: Path) -> None:
    vi = _import_vector()
    idx = vi.VectorIndex(tmp_path / "kb.db", embedder=MockEmbedder())
    try:
        idx.upsert(
            entity_id="f-1", entity_type="finding",
            text="alpha", metadata={"tags": ["timing", "spi"]},
        )
        idx.upsert(
            entity_id="f-2", entity_type="finding",
            text="beta", metadata={"tags": ["security"]},
        )
        spi_only = idx.search("anything", filters={"tags": ["spi"]})
        ids = {r.entity_id for r in spi_only}
        assert "f-1" in ids
        assert "f-2" not in ids
    finally:
        idx.close()


@needs_sqlite_vec
def test_search_bm25_finds_keyword_match(tmp_path: Path) -> None:
    """BM25 search ranks keyword matches without needing the embedder."""
    vi = _import_vector()
    idx = vi.VectorIndex(tmp_path / "kb.db", embedder=MockEmbedder())
    try:
        idx.upsert(
            entity_id="f-spi", entity_type="finding",
            text="SPI clock exceeds datasheet maximum frequency",
            metadata={"file": "src/spi.c"},
        )
        idx.upsert(
            entity_id="f-watchdog", entity_type="finding",
            text="watchdog reset triggered by stack overflow",
            metadata={"file": "src/wdt.c"},
        )
        results = idx.search("SPI clock", mode="bm25")
        ids = [r.entity_id for r in results]
        assert "f-spi" in ids
        # f-spi should rank ABOVE f-watchdog (no SPI tokens at all)
        assert ids[0] == "f-spi"
    finally:
        idx.close()


@needs_sqlite_vec
def test_search_bm25_respects_filters(tmp_path: Path) -> None:
    vi = _import_vector()
    idx = vi.VectorIndex(tmp_path / "kb.db", embedder=MockEmbedder())
    try:
        idx.upsert(entity_id="f-1", entity_type="finding",
                   text="alpha beta gamma", metadata={"severity": "high"})
        idx.upsert(entity_id="d-1", entity_type="decision",
                   text="alpha beta gamma", metadata={})
        # Filter restricts to findings
        results = idx.search("alpha", mode="bm25",
                             filters={"entity_type": "finding"})
        assert all(r.entity_type == "finding" for r in results)
    finally:
        idx.close()


@needs_sqlite_vec
def test_search_hybrid_merges_vec_and_bm25(tmp_path: Path) -> None:
    vi = _import_vector()
    idx = vi.VectorIndex(tmp_path / "kb.db", embedder=MockEmbedder())
    try:
        idx.upsert(entity_id="f-a", entity_type="finding",
                   text="SPI clock exceeds datasheet maximum",
                   metadata={"file": "src/spi.c"})
        idx.upsert(entity_id="f-b", entity_type="finding",
                   text="ADC sample rate too high",
                   metadata={"file": "src/adc.c"})
        results = idx.search("SPI clock", mode="hybrid")
        # Hybrid produces results; BM25 portion matches the SPI finding
        ids = [r.entity_id for r in results]
        assert "f-a" in ids
        # Scores in [0, 1]
        assert all(0.0 <= r.score <= 1.0 for r in results)
    finally:
        idx.close()


@needs_sqlite_vec
def test_search_unknown_mode_raises(tmp_path: Path) -> None:
    vi = _import_vector()
    idx = vi.VectorIndex(tmp_path / "kb.db", embedder=MockEmbedder())
    try:
        idx.upsert(entity_id="f", entity_type="finding",
                   text="anything", metadata={})
        try:
            idx.search("x", mode="not_a_mode")
        except ValueError as exc:
            assert "not_a_mode" in str(exc)
        else:
            raise AssertionError("expected ValueError")
    finally:
        idx.close()


@needs_sqlite_vec
def test_search_bm25_handles_punctuation(tmp_path: Path) -> None:
    """User queries with FTS5-special chars (':', '"', '-') must not crash."""
    vi = _import_vector()
    idx = vi.VectorIndex(tmp_path / "kb.db", embedder=MockEmbedder())
    try:
        idx.upsert(entity_id="f", entity_type="finding",
                   text="SPI clock too fast", metadata={})
        # Should not raise even with FTS5-special chars in query
        results = idx.search('SPI: "clock" - too fast?', mode="bm25")
        assert isinstance(results, list)
    finally:
        idx.close()


@needs_sqlite_vec
def test_rebuild_idempotent(tmp_path: Path) -> None:
    vi = _import_vector()
    config = SuiteConfig(storage_root=str(tmp_path / "kb"))

    # Plant fake findings + decisions on disk
    sess_dir = config.tool_sessions_path("review") / "s-1"
    sess_dir.mkdir(parents=True, exist_ok=True)
    (sess_dir / "findings.jsonl").write_text(
        json.dumps({"id": "f-1", "title": "alpha", "actual": "beta"}) + "\n"
        + json.dumps({"id": "f-2", "title": "gamma", "actual": "delta"}) + "\n",
        encoding="utf-8",
    )
    config.decisions_path.mkdir(parents=True, exist_ok=True)
    (config.decisions_path / "decisions.jsonl").write_text(
        json.dumps({
            "id": "adr-1", "title": "Picked X", "rationale": "best fit",
            "consequences": ["maintainable"], "status": "accepted",
        }) + "\n",
        encoding="utf-8",
    )

    e = MockEmbedder()
    idx = vi.VectorIndex(config.vector_index_path, embedder=e)
    try:
        stats1 = idx.rebuild_from_jsonl(config, scope="all")
        assert stats1.indexed == 3
        assert idx.count() == 3
        embeds_after_first = e.encode_calls

        # Rebuild again with unchanged JSONL -> no new embeddings
        stats2 = idx.rebuild_from_jsonl(config, scope="all")
        assert idx.count() == 3
        # Each upsert with same text_hash -> 0 new encode() calls
        assert e.encode_calls == embeds_after_first
    finally:
        idx.close()


# ─── on_write integration tests (no vector index required) ─────────────────


def test_finding_writer_invokes_on_write(tmp_path: Path) -> None:
    config = SuiteConfig(storage_root=str(tmp_path / "kb"))
    captured: list[dict] = []
    writer = FindingWriter(
        "review", "s-1", config,
        on_write=lambda f: captured.append(dict(f)),
    )
    fid = writer.post({"title": "test", "severity": "low"})
    assert len(captured) == 1
    assert captured[0]["id"] == fid


def test_finding_writer_swallows_on_write_exception(tmp_path: Path) -> None:
    """A failing hook must not break the JSONL append (durable write wins)."""
    config = SuiteConfig(storage_root=str(tmp_path / "kb"))

    def bad_hook(_finding: dict) -> None:
        raise RuntimeError("indexer down")

    writer = FindingWriter("review", "s-1", config, on_write=bad_hook)
    fid = writer.post({"title": "test"})
    assert fid
    # Verify finding is on disk despite hook failure
    findings_path = config.tool_sessions_path("review") / "s-1" / "findings.jsonl"
    assert findings_path.exists()
    assert findings_path.read_text(encoding="utf-8").strip() != ""


def test_finding_writer_post_batch_invokes_on_write_per_entry(
    tmp_path: Path,
) -> None:
    config = SuiteConfig(storage_root=str(tmp_path / "kb"))
    captured: list[dict] = []
    writer = FindingWriter(
        "review", "s-1", config,
        on_write=lambda f: captured.append(dict(f)),
    )
    ids = writer.post_batch([
        {"title": "a"}, {"title": "b"}, {"title": "c"},
    ])
    assert len(ids) == 3
    assert len(captured) == 3
    assert {c["title"] for c in captured} == {"a", "b", "c"}


def test_decision_store_invokes_on_write_on_append(tmp_path: Path) -> None:
    captured: list[dict] = []
    store = DecisionStore(
        tmp_path / "decisions.jsonl",
        on_write=lambda d: captured.append(dict(d)),
    )
    decision = store.append(title="ADR-001", rationale="because", status="accepted")
    assert len(captured) == 1
    assert captured[0]["title"] == "ADR-001"
    assert captured[0]["id"] == decision.id


def test_decision_store_invokes_on_write_on_status_update(tmp_path: Path) -> None:
    """Status updates must re-fire on_write so the index reflects new status."""
    captured: list[dict] = []
    store = DecisionStore(
        tmp_path / "decisions.jsonl",
        on_write=lambda d: captured.append(dict(d)),
    )
    decision = store.append(title="X", status="proposed")
    captured.clear()
    ok = store.update_status(decision.id, "accepted")
    assert ok
    assert len(captured) == 1
    assert captured[0]["status"] == "accepted"
    # Missing decision -> no hook call
    captured.clear()
    assert store.update_status("nope", "rejected") is False
    assert captured == []
