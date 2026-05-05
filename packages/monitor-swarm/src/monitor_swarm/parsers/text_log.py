"""Text-log trace parser — regex-driven, with timestamp + message extraction.

Default pattern matches common firmware-log shapes:

    [12.345678] [INFO ] adc: t_conv = 137 us
    12.345678 INFO adc: t_conv=137us
    2026-05-05T12:34:56.123Z DEBUG main: SPI transaction 0xAB

Users with non-standard formats provide their own regex via
``log_pattern``. Required named groups: ``timestamp`` and ``message``.
Optional: ``channel`` / ``level``.

Timestamps are normalised to microseconds-from-start. Plain numeric
timestamps are treated as seconds; ISO-8601 timestamps are converted
relative to the first event's timestamp.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ..models import TraceEvent

_log = logging.getLogger("monitor_swarm.parsers.text_log")


# Named groups: timestamp (numeric or ISO), level (optional),
# channel (optional, before colon), message.
DEFAULT_LOG_PATTERN = re.compile(
    r"^\s*"
    r"\[?(?P<timestamp>[\d.]+|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\]?"
    r"\s+"
    r"(?:\[?(?P<level>DEBUG|INFO|WARN|WARNING|ERROR|FATAL|TRACE)\]?\s+)?"
    r"(?:(?P<channel>[\w./-]+):\s+)?"
    r"(?P<message>.+?)\s*$"
)


# ReDoS guard: user-supplied log_pattern is run against every line of an
# arbitrarily-large trace file. Catastrophic backtracking on a hostile or
# careless pattern can hang the MCP server. Python's `re` has no native
# timeout, so we validate at compile time:
#   1. cap pattern length (long patterns are rarely intended)
#   2. reject classic nested-quantifier shapes like (X+)+ / (X*)* / (X+)*
#   3. reject consecutive greedy dot-stars / dot-pluses
_MAX_LOG_PATTERN_LEN = 500
_REDOS_HEURISTIC = re.compile(
    r"\([^)]*[+*]\)\s*[+*]"      # (X+)+, (X*)*, (X+)*, (X*)+, ...
    r"|"
    r"(\.[+*]){2,}",             # .* .+ .* ... two or more consecutive
)


def _validate_log_pattern(pattern: str) -> str | None:
    """Return None if pattern is safe; otherwise an error message."""
    if not isinstance(pattern, str):
        return "log_pattern must be a string"
    if len(pattern) > _MAX_LOG_PATTERN_LEN:
        return (
            f"log_pattern too long ({len(pattern)} > "
            f"{_MAX_LOG_PATTERN_LEN} chars) — possible ReDoS, refusing to compile"
        )
    if _REDOS_HEURISTIC.search(pattern):
        return (
            "log_pattern contains nested quantifiers / consecutive .* (potential "
            "ReDoS via catastrophic backtracking) — refusing to compile"
        )
    return None


def _parse_timestamp(raw: str) -> tuple[float, bool]:
    """Return (timestamp_us, is_absolute_iso).

    Returns absolute *epoch microseconds* when ``raw`` is ISO-8601;
    relative microseconds-from-zero otherwise.
    """
    raw = raw.strip()
    # Numeric (seconds with optional fraction)
    if re.fullmatch(r"[\d.]+", raw):
        try:
            return float(raw) * 1_000_000.0, False
        except ValueError:
            return 0.0, False
    # ISO-8601
    cleaned = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1_000_000.0, True
    except ValueError:
        return 0.0, False


def parse_text_log(
    trace_path: str | Path,
    *,
    log_pattern: str | re.Pattern | None = None,
) -> tuple[list[TraceEvent], list[str]]:
    """Parse a text log into ``TraceEvent``s.

    Returns ``(events, warnings)``. Warnings are accumulated as strings
    for unparseable lines (typically up to the first ten — beyond that
    we stop noting individual lines and just count).
    """
    if log_pattern is None:
        pattern: re.Pattern = DEFAULT_LOG_PATTERN
    elif isinstance(log_pattern, re.Pattern):
        pattern = log_pattern
    else:
        err = _validate_log_pattern(log_pattern)
        if err is not None:
            return [], [err]
        try:
            pattern = re.compile(log_pattern)
        except re.error as exc:
            return [], [f"log_pattern is not a valid regex: {exc}"]

    path = Path(trace_path)
    if not path.is_file():
        return [], [f"Trace file not found: {trace_path}"]

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], [f"Cannot read trace file: {exc}"]

    events: list[TraceEvent] = []
    warnings: list[str] = []
    iso_offset_us: float | None = None
    skipped_count = 0

    for idx, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        m = pattern.match(line)
        if not m:
            skipped_count += 1
            if len(warnings) < 10:
                warnings.append(f"Line {idx}: no match for pattern")
            continue
        gd = m.groupdict()
        ts_raw = gd.get("timestamp") or "0"
        ts_us, is_iso = _parse_timestamp(ts_raw)
        if is_iso:
            if iso_offset_us is None:
                iso_offset_us = ts_us
            ts_us -= iso_offset_us

        events.append(TraceEvent(
            timestamp_us=ts_us,
            channel=gd.get("channel") or gd.get("level") or "log",
            kind="log",
            value=gd.get("message") or "",
            raw_line=line,
            line_number=idx,
        ))

    if skipped_count > 10:
        warnings.append(
            f"... and {skipped_count - 10} more lines unparseable "
            f"(consider providing a custom log_pattern)"
        )
    return events, warnings
