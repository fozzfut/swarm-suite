"""Hard input limits for storage engines + a shared LRU cache for in-memory records.

Two enterprise-grade concerns ride on this module:

  1. **Bounded inputs.** Every storage record has string fields that
     ultimately come from an MCP tool argument -- which is to say, from
     untrusted callers. Without limits a 100MB rationale lands in
     judging.json and the next process boot OOMs reading it. The caps
     here are deliberately generous (tens of KB for text, low MB for
     payloads) and uniform across modules so operators only need to
     tune one place.

  2. **Bounded in-memory caches.** JudgingEngine / VerificationStore /
     PgveStore / FlowStore all keep loaded records in `self._records`
     and never evict. For a long-running server with thousands of
     records the cache grows linearly forever. `BoundedRecordCache`
     wraps the dict pattern with a max-size LRU eviction; on-disk
     records persist, the cache just keeps the newest in memory and
     re-loads older ones on demand.

Both are intentionally lightweight: no new dependency, no async, no
clever data structure -- a Python dict with eviction is enough at the
expected scale (~1000 records, ~10s of MB total).
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from typing import Generic, Iterator, TypeVar


# ---------------------------------------------------------------------------
# Input length limits
# ---------------------------------------------------------------------------

# Per-field text fields (subject, summary, rationale, feedback, content,
# task_spec, source). Generous for verbose human text but bounded.
MAX_TEXT_LEN: int = 65_536

# Per-record JSON-encoded payload/data dicts. 1 MiB on the wire.
MAX_PAYLOAD_BYTES: int = 1_048_576

# Per-aggregate fan-out: how many sub-items can belong to one record.
MAX_DIMENSIONS: int = 32          # judging dimensions per Judging
MAX_SUGGESTED_CHANGES: int = 64   # changes per Judgment
MAX_FOLLOW_UPS: int = 64          # follow-ups per Verdict
MAX_BLOCKING_ISSUES: int = 64     # blocking issues per VerificationVerdict
MAX_EVIDENCE_PER_REPORT: int = 256
MAX_CANDIDATES_HARD: int = 50     # absolute cap on PgveSession.max_candidates

# Default in-memory record-cache size for engines.
DEFAULT_MAX_RECORDS: int = 1_000


# ---------------------------------------------------------------------------
# Validation helpers (raise ValueError -> mcp_safe maps to INVALID_PARAMS)
# ---------------------------------------------------------------------------


def check_text(value: str, field_name: str, *, max_len: int = MAX_TEXT_LEN) -> None:
    """Reject `value` if it exceeds `max_len` characters.

    Used in __post_init__ for any user-supplied text field. Cheap;
    O(1) since `len(str)` is constant time in CPython.
    """
    if len(value) > max_len:
        raise ValueError(
            f"{field_name} length {len(value)} exceeds limit {max_len}"
        )


def check_payload_size(payload: dict, field_name: str,
                       *, max_bytes: int = MAX_PAYLOAD_BYTES) -> None:
    """Reject `payload` if its JSON encoding exceeds `max_bytes`.

    Encodes once with the same settings the store uses; for typical
    small payloads this is microseconds.
    """
    try:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} is not JSON-serialisable: {exc}") from exc
    if len(encoded) > max_bytes:
        raise ValueError(
            f"{field_name} JSON size {len(encoded)} bytes exceeds limit {max_bytes}"
        )


def check_count(items: list | tuple, field_name: str, max_count: int) -> None:
    """Reject if `items` has more than `max_count` elements."""
    if len(items) > max_count:
        raise ValueError(
            f"{field_name} count {len(items)} exceeds limit {max_count}"
        )


# ---------------------------------------------------------------------------
# BoundedRecordCache -- LRU cache for engine in-memory state
# ---------------------------------------------------------------------------


_R = TypeVar("_R")


class BoundedRecordCache(Generic[_R]):
    """Thread-safe LRU cache of records keyed by string id.

    On `put`, evicts the oldest (first-inserted) record once the cache
    exceeds `max_records`. Tracks size via OrderedDict's insertion order.
    Eviction is in-memory only -- callers are expected to persist to
    disk separately and reload on miss via `_get_or_load`.

    Designed as a drop-in for `self._records: dict[str, R]`. The engine
    does the disk reload itself; the cache just bounds RAM.
    """

    def __init__(self, max_records: int = DEFAULT_MAX_RECORDS) -> None:
        if max_records < 1:
            raise ValueError("max_records must be >= 1")
        self._max = max_records
        self._items: "OrderedDict[str, _R]" = OrderedDict()
        self._lock = threading.RLock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._items

    def get(self, key: str) -> _R | None:
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                # Touch -> mark as most-recent.
                self._items.move_to_end(key)
            return value

    def put(self, key: str, value: _R) -> None:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
            self._items[key] = value
            while len(self._items) > self._max:
                # popitem(last=False) drops the oldest.
                self._items.popitem(last=False)

    def values(self) -> list[_R]:
        with self._lock:
            return list(self._items.values())

    def items(self) -> list[tuple[str, _R]]:
        with self._lock:
            return list(self._items.items())

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._items.keys())

    def pop(self, key: str, default: _R | None = None) -> _R | None:
        with self._lock:
            return self._items.pop(key, default)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(list(self._items.keys()))

    @property
    def max_records(self) -> int:
        return self._max
