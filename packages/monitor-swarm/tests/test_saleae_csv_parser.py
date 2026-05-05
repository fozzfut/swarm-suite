"""Tests for the Saleae Logic2 CSV parser."""

from pathlib import Path

import pytest

from monitor_swarm.parsers.saleae_csv import parse_saleae_csv


def _write(p: Path, content: str) -> Path:
    p.write_text(content, encoding="utf-8")
    return p


def test_digital_export_emits_one_event_per_edge(tmp_path: Path) -> None:
    csv = _write(tmp_path / "digital.csv",
                 "Time [s], Channel 0, Channel 1\n"
                 "0.000000, 0, 0\n"
                 "0.000010, 1, 0\n"   # rising on Ch0
                 "0.000020, 1, 1\n"   # rising on Ch1
                 "0.000030, 0, 1\n")  # falling on Ch0
    events, warnings = parse_saleae_csv(csv)
    assert warnings == []
    # 3 edges total
    assert len(events) == 3
    assert events[0].kind == "rising"
    assert events[1].kind == "rising"
    assert events[2].kind == "falling"
    # First edge at 10us relative to first sample
    assert events[0].timestamp_us == pytest.approx(10.0, rel=1e-6)


def test_protocol_export_emits_one_event_per_row(tmp_path: Path) -> None:
    csv = _write(tmp_path / "spi.csv",
                 "Time [s], Type, MOSI, MISO\n"
                 "0.001, SPI, 0xAB, 0xCD\n"
                 "0.002, SPI, 0xFF, 0x00\n")
    events, _ = parse_saleae_csv(csv)
    assert len(events) == 2
    assert events[0].kind == "transaction"
    assert events[0].channel == "SPI"
    assert "MOSI=0xAB" in events[0].value


def test_first_sample_is_relative_zero(tmp_path: Path) -> None:
    csv = _write(tmp_path / "d.csv",
                 "Time [s], Channel 0\n"
                 "100.000000, 0\n"
                 "100.000005, 1\n")
    events, _ = parse_saleae_csv(csv)
    assert len(events) == 1
    assert events[0].timestamp_us == pytest.approx(5.0, rel=1e-6)


def test_unparseable_time_skipped_with_warning(tmp_path: Path) -> None:
    csv = _write(tmp_path / "d.csv",
                 "Time [s], Channel 0\n"
                 "0.000, 0\n"
                 "BAD_TIME, 1\n"
                 "0.020, 1\n")
    events, warnings = parse_saleae_csv(csv)
    # 0 → 1 detected at 0.020 (skipping the bad row), one rising edge.
    assert len(events) == 1
    assert any("unparseable time" in w for w in warnings)


def test_missing_file(tmp_path: Path) -> None:
    events, warnings = parse_saleae_csv(tmp_path / "nope.csv")
    assert events == []
    assert any("not found" in w.lower() for w in warnings)


def test_empty_csv(tmp_path: Path) -> None:
    csv = _write(tmp_path / "empty.csv", "")
    events, warnings = parse_saleae_csv(csv)
    assert events == []
    assert warnings  # at least one warning
