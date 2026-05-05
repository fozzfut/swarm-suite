"""Tests for the text-log parser."""

from pathlib import Path

import pytest

from monitor_swarm.parsers.text_log import parse_text_log


def _write(p: Path, content: str) -> Path:
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_simple_bracket_format(tmp_path: Path) -> None:
    log = _write(tmp_path / "trace.log",
                 "[12.345678] [INFO] adc: t_conv = 137 us\n"
                 "[12.347000] [INFO] main: ready\n")
    events, warnings = parse_text_log(log)
    assert warnings == []
    assert len(events) == 2
    assert "t_conv" in events[0].value
    assert events[0].channel == "adc"
    # timestamp converted to microseconds
    assert events[0].timestamp_us == pytest.approx(12.345678 * 1_000_000.0, rel=1e-6)


def test_parse_iso_timestamp_normalises_to_zero(tmp_path: Path) -> None:
    log = _write(tmp_path / "trace.log",
                 "2026-05-05T12:00:00.000Z DEBUG main: ADC start\n"
                 "2026-05-05T12:00:00.500Z DEBUG main: ADC done\n")
    events, _ = parse_text_log(log)
    assert len(events) == 2
    assert events[0].timestamp_us == 0.0
    # 500 ms in microseconds
    assert events[1].timestamp_us == pytest.approx(500_000.0, rel=1e-6)


def test_unparseable_lines_collected_as_warnings(tmp_path: Path) -> None:
    log = _write(tmp_path / "trace.log",
                 "[1.0] [INFO] ok: hello\n"
                 "garbage line\n"
                 "another garbage\n")
    events, warnings = parse_text_log(log)
    assert len(events) == 1
    assert any("garbage" in w or "no match" in w for w in warnings)


def test_custom_log_pattern(tmp_path: Path) -> None:
    log = _write(tmp_path / "trace.log",
                 "T+0.001 :: spi :: t_setup=4ns\n"
                 "T+0.002 :: spi :: t_hold=2ns\n")
    pattern = (
        r"^T\+(?P<timestamp>[\d.]+)\s*::\s*"
        r"(?P<channel>\w+)\s*::\s*"
        r"(?P<message>.+)$"
    )
    events, warnings = parse_text_log(log, log_pattern=pattern)
    assert warnings == []
    assert [e.channel for e in events] == ["spi", "spi"]
    assert "t_setup=4ns" in events[0].value


def test_missing_file_returns_warning(tmp_path: Path) -> None:
    events, warnings = parse_text_log(tmp_path / "does-not-exist.log")
    assert events == []
    assert any("not found" in w.lower() for w in warnings)


def test_empty_lines_skipped(tmp_path: Path) -> None:
    log = _write(tmp_path / "trace.log",
                 "[1.0] [INFO] ok: hello\n\n\n[2.0] [INFO] ok: world\n")
    events, _ = parse_text_log(log)
    assert len(events) == 2


def test_overflow_warning_on_many_unparseable(tmp_path: Path) -> None:
    """More than 10 unparseable lines should collapse to a count summary."""
    bad_block = "garbage\n" * 30
    log = _write(tmp_path / "trace.log",
                 "[1.0] [INFO] ok: x\n" + bad_block)
    _, warnings = parse_text_log(log)
    # First 10 lines listed plus a summary
    assert any("more lines unparseable" in w for w in warnings)
