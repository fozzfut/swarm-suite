"""UTC ISO 8601 timestamp -- the only timestamp helper in the suite.

Every persisted record uses this to populate `created_at` / `updated_at`
fields. Local-time timestamps are forbidden -- they break cross-machine
log correlation and time-window queries.
"""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """Return current UTC time as an ISO 8601 string with timezone offset."""
    return datetime.now(timezone.utc).isoformat()
