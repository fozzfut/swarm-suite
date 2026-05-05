"""Tests for timing-measurement extraction + violation detection."""

from monitor_swarm.detectors.timing_violation import (
    detect_timing_violations,
    extract_timing_measurements,
)
from monitor_swarm.models import TraceEvent


def _ev(text: str, ts_us: float = 0.0, line: int = 1) -> TraceEvent:
    return TraceEvent(timestamp_us=ts_us, channel="log", kind="log",
                      value=text, raw_line=text, line_number=line)


# ─── extraction ────────────────────────────────────────────────────────────


def test_extract_param_equals_value_us() -> None:
    measurements = extract_timing_measurements([
        _ev("adc: t_conv=137us"),
    ])
    assert len(measurements) == 1
    m = measurements[0]
    assert m.parameter == "t_conv"
    assert m.measured_us == 137.0


def test_extract_param_with_spaces_and_unit_variants() -> None:
    events = [
        _ev("t_setup = 4 ns"),
        _ev("ADC conversion took 0.137 ms"),
        _ev("startup: 1.5 s"),
    ]
    ms = extract_timing_measurements(events)
    by_name = {m.parameter: m for m in ms}
    assert by_name["t_setup"].measured_us == 0.004  # 4 ns
    assert by_name["conversion"].measured_us == 137.0  # 0.137 ms = 137 us
    assert by_name["startup"].measured_us == 1_500_000.0  # 1.5 s


def test_extract_with_micro_symbol() -> None:
    ms = extract_timing_measurements([_ev("t_pulse = 50 µs")])
    assert len(ms) == 1
    assert ms[0].measured_us == 50.0


def test_extract_ignores_non_timing_text() -> None:
    ms = extract_timing_measurements([
        _ev("hello world"),
        _ev("counter = 42"),
        _ev("temperature = 25 C"),
    ])
    assert ms == []


# ─── detection ──────────────────────────────────────────────────────────────


def _constraint(parameter: str, *, max_value: str | None = None,
                min_value: str | None = None, unit: str = "us",
                critical: bool = False, source: str = "Datasheet T1") -> dict:
    return {
        "parameter": parameter,
        "min_value": min_value or "",
        "max_value": max_value or "",
        "unit": unit,
        "source": source,
        "critical": critical,
    }


def test_violation_above_max() -> None:
    ms = extract_timing_measurements([_ev("adc: t_conv=137us", line=10)])
    findings = detect_timing_violations(
        ms, [_constraint("t_conv", max_value="120", unit="us")],
        trace_path="trace.log",
    )
    assert len(findings) == 1
    f = findings[0]
    assert f.measured_us == 137.0
    assert f.expected_max_us == 120.0
    assert f.severity == "high"
    assert f.source_line == 10


def test_violation_below_min() -> None:
    ms = extract_timing_measurements([_ev("t_setup = 1 ns")])
    findings = detect_timing_violations(
        ms, [_constraint("t_setup", min_value="3", unit="ns")],
    )
    assert len(findings) == 1
    assert findings[0].measured_us == 0.001


def test_in_bounds_no_finding() -> None:
    ms = extract_timing_measurements([_ev("t_conv=100us")])
    findings = detect_timing_violations(
        ms, [_constraint("t_conv", min_value="50", max_value="120", unit="us")],
    )
    assert findings == []


def test_critical_constraint_yields_critical_severity() -> None:
    ms = extract_timing_measurements([_ev("t_setup = 1 ns")])
    findings = detect_timing_violations(
        ms, [_constraint("t_setup", min_value="3", unit="ns", critical=True)],
    )
    assert findings[0].severity == "critical"


def test_constraint_with_t_prefix_normalised() -> None:
    """Spec calls it 't_conv', log says 'conv = 137us' — should still match."""
    ms = extract_timing_measurements([_ev("conv = 137us")])
    findings = detect_timing_violations(
        ms, [_constraint("t_conv", max_value="120", unit="us")],
    )
    assert len(findings) == 1


def test_unrelated_constraint_does_not_emit() -> None:
    ms = extract_timing_measurements([_ev("t_unrelated=999us")])
    findings = detect_timing_violations(
        ms, [_constraint("t_other", max_value="100", unit="us")],
    )
    assert findings == []


def test_finding_dict_shape_matches_swarm_kb_writer_contract() -> None:
    ms = extract_timing_measurements([_ev("t_conv=137us", line=42)])
    findings = detect_timing_violations(
        ms, [_constraint("t_conv", max_value="120", unit="us",
                         source="STM32F407 Table 47")],
        trace_path="trace.log",
        component_name="STM32F407VG",
    )
    d = findings[0].to_finding_dict()
    # Required fields per FindingWriter.post()
    for key in ("title", "severity", "category", "expert_role",
                "file", "line_start", "actual", "expected", "snippet",
                "source_ref", "suggestion_action", "suggestion_detail",
                "confidence", "tags", "status"):
        assert key in d, f"missing key: {key}"
    assert d["category"] == "timing-violation"
    assert d["expert_role"] == "timing-analyst"
    assert d["source_ref"] == "STM32F407 Table 47"
    assert "STM32F407VG" in d["tags"]
