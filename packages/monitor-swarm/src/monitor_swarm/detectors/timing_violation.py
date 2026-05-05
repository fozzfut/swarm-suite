"""Timing-violation detector.

Two-step pipeline:

1. ``extract_timing_measurements(events)`` — scan TraceEvent values for
   inline timing parameters of the shape ``<param>=<value><unit>`` or
   ``<param> took <value><unit>``. Returns a list of TimingMeasurement.

2. ``detect_timing_violations(measurements, spec_constraints)`` — for
   each measurement whose parameter name matches a spec constraint,
   compare against ``min_value`` / ``max_value`` from the datasheet and
   emit a ``ViolationFinding`` if out of bounds.

The spec_constraints input is the list returned by spec-swarm's
``spec_get_timing`` (see ``packages/spec-swarm/src/spec_swarm/models.py``
:class:`TimingConstraint`). It's deliberately structurally typed (dict
with parameter / min_value / max_value / unit) so this module doesn't
import spec-swarm at runtime — clean layering per
``docs/architecture/layering.md``.
"""

from __future__ import annotations

import logging
import re

from ..models import TimingMeasurement, TraceEvent, ViolationFinding

_log = logging.getLogger("monitor_swarm.detectors.timing_violation")


# "<param>=<value><unit>", "<param> took <value><unit>",
# "<param>: <value><unit>", "<param> = <value> <unit>"
_TIMING_PATTERN = re.compile(
    r"\b(?P<param>[a-zA-Z_][\w]*)"
    r"\s*(?:=|:|\btook\b)\s*"
    r"(?P<value>[\d.]+)\s*"
    r"(?P<unit>ns|us|µs|ms|s|MHz|kHz|Hz)\b",
    re.IGNORECASE,
)

# Convert any supported unit to microseconds.
_UNIT_TO_US: dict[str, float] = {
    "ns": 1e-3,
    "us": 1.0,
    "µs": 1.0,
    "ms": 1e3,
    "s": 1e6,
}


def _to_us(value: float, unit: str) -> float | None:
    factor = _UNIT_TO_US.get(unit.lower())
    if factor is None:
        return None
    return value * factor


def _parse_constraint_value(raw: str | None, unit_hint: str = "us") -> float | None:
    """Parse a spec constraint value string like '120 us' or '0.1ms' into us."""
    if raw is None or not str(raw).strip():
        return None
    s = str(raw).strip()
    m = re.match(r"^([\d.]+)\s*([a-zA-Zµ]*)$", s)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or unit_hint).lower()
    return _to_us(v, unit)


def extract_timing_measurements(
    events: list[TraceEvent],
) -> list[TimingMeasurement]:
    """Pull timing measurements out of trace events' value strings."""
    out: list[TimingMeasurement] = []
    for ev in events:
        text = ev.value or ""
        for m in _TIMING_PATTERN.finditer(text):
            param = m.group("param")
            try:
                val = float(m.group("value"))
            except ValueError:
                continue
            unit = m.group("unit")
            us = _to_us(val, unit)
            if us is None:
                continue
            out.append(TimingMeasurement(
                parameter=param,
                measured_us=us,
                unit="us",
                source_event=ev,
                raw_match=m.group(0),
            ))
    return out


def _normalise_param(name: str) -> str:
    """Strip prefixes / spaces / case for lenient matching of constraint names."""
    s = (name or "").strip().lower()
    # Common prefixes that don't change the parameter identity:
    for pref in ("t_", "timing_"):
        if s.startswith(pref):
            s = s[len(pref):]
            break
    return s.replace(" ", "_").replace("-", "_")


def detect_timing_violations(
    measurements: list[TimingMeasurement],
    spec_constraints: list[dict],
    *,
    trace_path: str = "",
    spec_session_id: str = "",
    component_name: str = "",
) -> list[ViolationFinding]:
    """Cross-reference measurements vs spec constraints; emit violations.

    ``spec_constraints`` is the list of dicts returned by
    ``spec_get_timing`` (each has parameter, min_value, max_value,
    unit, condition, source, critical).
    """
    if not measurements or not spec_constraints:
        return []

    # Index constraints by normalised parameter name.
    by_param: dict[str, list[dict]] = {}
    for c in spec_constraints:
        if not isinstance(c, dict):
            continue
        key = _normalise_param(str(c.get("parameter", "")))
        if key:
            by_param.setdefault(key, []).append(c)

    findings: list[ViolationFinding] = []

    for meas in measurements:
        key = _normalise_param(meas.parameter)
        candidates = by_param.get(key)
        if not candidates:
            continue
        for c in candidates:
            unit_hint = (str(c.get("unit") or "us")).lower()
            min_us = _parse_constraint_value(c.get("min_value"), unit_hint)
            max_us = _parse_constraint_value(c.get("max_value"), unit_hint)
            if min_us is None and max_us is None:
                continue

            in_bounds = True
            if min_us is not None and meas.measured_us < min_us:
                in_bounds = False
            if max_us is not None and meas.measured_us > max_us:
                in_bounds = False
            if in_bounds:
                continue

            critical = bool(c.get("critical", False))
            severity = "critical" if critical else "high"
            ev = meas.source_event
            findings.append(ViolationFinding(
                parameter=meas.parameter,
                measured_us=meas.measured_us,
                expected_min_us=min_us,
                expected_max_us=max_us,
                constraint_source=str(c.get("source") or ""),
                severity=severity,
                trace_path=trace_path,
                source_line=ev.line_number if ev else 0,
                source_timestamp_us=ev.timestamp_us if ev else 0.0,
                raw_line=ev.raw_line if ev else "",
                spec_session_id=spec_session_id,
                component_name=component_name,
            ))
            break  # one finding per measurement, even if multiple constraints match

    return findings
