"""Saleae Logic2 CSV trace parser.

Saleae Logic2 exports two distinct CSV shapes:

1. **Digital signal export** — header ``Time [s], Channel 0, Channel 1, ...``;
   each row is a sample with channel levels. We emit one TraceEvent per
   detected edge (rising / falling) per channel.

2. **Protocol analyzer export** — header includes columns like ``Type``,
   ``Value``, ``Address``, etc. Each row is a decoded transaction. We emit
   one TraceEvent per row with ``kind = "transaction"``.

The first column is always assumed to be a time in seconds; converted
to microseconds-from-start on output.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from ..models import TraceEvent

_log = logging.getLogger("monitor_swarm.parsers.saleae_csv")


def _is_digital_export(header: list[str]) -> bool:
    return any(c.lower().startswith("channel") for c in header[1:])


def _parse_float(raw: str) -> float | None:
    try:
        return float(raw.strip())
    except ValueError:
        return None


def parse_saleae_csv(
    trace_path: str | Path,
) -> tuple[list[TraceEvent], list[str]]:
    """Parse a Saleae Logic2 CSV export.

    Returns ``(events, warnings)``. For digital exports, edges (rising /
    falling) are emitted; signal levels that don't change produce no
    events. For protocol exports, every row becomes one event.
    """
    path = Path(trace_path)
    if not path.is_file():
        return [], [f"Trace file not found: {trace_path}"]

    events: list[TraceEvent] = []
    warnings: list[str] = []

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], [f"Cannot read trace file: {exc}"]

    reader = csv.reader(text.splitlines())
    rows = list(reader)
    if not rows:
        return [], ["Empty CSV"]

    header = [c.strip() for c in rows[0]]
    if not header:
        return [], ["No header row"]

    # First column should be a time-like header.
    time_col = 0
    if "time" not in header[0].lower():
        warnings.append(
            f"First CSV column header is {header[0]!r}; expected 'Time [s]'. "
            "Treating first column as time anyway."
        )

    digital = _is_digital_export(header)
    t0_us: float | None = None

    if digital:
        # Track previous level per channel to emit edge events.
        prev_levels: dict[int, str] = {}
        channels = [(i, name) for i, name in enumerate(header) if i != time_col]
        for row_idx, row in enumerate(rows[1:], start=2):
            if len(row) < len(header):
                warnings.append(
                    f"Line {row_idx}: row has {len(row)} fields, expected {len(header)}"
                )
                continue
            t_s = _parse_float(row[time_col])
            if t_s is None:
                warnings.append(f"Line {row_idx}: unparseable time {row[time_col]!r}")
                continue
            t_us = t_s * 1_000_000.0
            if t0_us is None:
                t0_us = t_us
            rel_us = t_us - t0_us

            for col_idx, ch_name in channels:
                level = (row[col_idx] or "").strip()
                if not level:
                    continue
                prev = prev_levels.get(col_idx)
                if prev is None:
                    prev_levels[col_idx] = level
                    continue
                if level != prev:
                    kind = "rising" if (prev, level) in (("0", "1"), ("L", "H")) else "falling"
                    events.append(TraceEvent(
                        timestamp_us=rel_us,
                        channel=ch_name,
                        kind=kind,
                        value=level,
                        raw_line=",".join(row),
                        line_number=row_idx,
                    ))
                    prev_levels[col_idx] = level
    else:
        # Protocol-decoded export: one event per row.
        for row_idx, row in enumerate(rows[1:], start=2):
            if len(row) < len(header):
                continue
            t_s = _parse_float(row[time_col])
            if t_s is None:
                warnings.append(f"Line {row_idx}: unparseable time {row[time_col]!r}")
                continue
            t_us = t_s * 1_000_000.0
            if t0_us is None:
                t0_us = t_us
            rel_us = t_us - t0_us

            # Try to find a channel name and a value
            ch_name = ""
            value_parts = []
            for col_idx, col_header in enumerate(header):
                if col_idx == time_col:
                    continue
                cell = (row[col_idx] or "").strip()
                if not cell:
                    continue
                lower = col_header.lower()
                if not ch_name and lower in ("type", "name", "channel", "analyzer"):
                    ch_name = cell
                else:
                    value_parts.append(f"{col_header}={cell}")

            events.append(TraceEvent(
                timestamp_us=rel_us,
                channel=ch_name or "transaction",
                kind="transaction",
                value="; ".join(value_parts),
                raw_line=",".join(row),
                line_number=row_idx,
            ))

    return events, warnings
