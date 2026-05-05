"""End-to-end smoke test for monitor-swarm server logic.

Exercises the analyze pipeline directly (without spinning up the MCP
server itself) — parser → measurement → detector → KB persistence —
to confirm the wiring is correct and findings land in
``~/.swarm-kb/monitor/sessions/<sid>/findings.jsonl``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm_kb.config import SuiteConfig
from swarm_kb.finding_reader import FindingReader
from swarm_kb.finding_writer import FindingWriter
from swarm_core.ids import generate_id

from monitor_swarm.detectors import (
    detect_timing_violations,
    extract_timing_measurements,
)
from monitor_swarm.parsers import parse_text_log


@pytest.fixture()
def kb_root(tmp_path: Path, monkeypatch) -> Path:
    """Isolated swarm-kb root for the test."""
    root = tmp_path / "kb"
    monkeypatch.setenv("HOME", str(tmp_path))  # macOS / Linux
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
    return root


def test_analyze_text_log_emits_finding_to_kb(kb_root: Path,
                                              tmp_path: Path) -> None:
    # 1. Plant a fake log with a timing line that violates a constraint
    log_path = tmp_path / "firmware.log"
    log_path.write_text(
        "[1.000000] [INFO] adc: t_conv = 137 us\n"
        "[1.000200] [INFO] main: ready\n",
        encoding="utf-8",
    )

    spec_constraints = [{
        "parameter": "t_conv",
        "max_value": "120",
        "unit": "us",
        "source": "Datasheet Table 47",
        "critical": False,
    }]

    # 2. Run the pipeline (mirroring server._monitor_analyze_trace logic)
    events, warnings = parse_text_log(log_path)
    assert warnings == []
    measurements = extract_timing_measurements(events)
    findings = detect_timing_violations(
        measurements, spec_constraints,
        trace_path=str(log_path),
        component_name="STM32F407",
    )
    assert len(findings) == 1
    assert findings[0].measured_us == 137.0

    # 3. Persist into the KB monitor session
    config = SuiteConfig(storage_root=str(kb_root))
    sid = f"mon-{generate_id('s', length=4)}"
    session_dir = config.tool_sessions_path("monitor") / sid
    session_dir.mkdir(parents=True, exist_ok=True)
    writer = FindingWriter("monitor", sid, config)
    for f in findings:
        writer.post(f.to_finding_dict())

    # 4. Read back and validate
    reader = FindingReader(session_dir)
    assert reader.exists()
    persisted = reader.read_all()
    assert len(persisted) == 1
    p = persisted[0]
    assert p["category"] == "timing-violation"
    assert p["expert_role"] == "timing-analyst"
    assert "t_conv" in p["title"]
    assert p["severity"] == "high"
    assert p["source_ref"] == "Datasheet Table 47"


def test_analyze_text_log_no_constraints_yields_no_findings(tmp_path: Path) -> None:
    log = tmp_path / "f.log"
    log.write_text("[1.0] [INFO] adc: t_conv = 137 us\n", encoding="utf-8")
    events, _ = parse_text_log(log)
    measurements = extract_timing_measurements(events)
    findings = detect_timing_violations(measurements, [],
                                        trace_path=str(log))
    assert findings == []


def test_constraint_with_no_bounds_is_ignored(tmp_path: Path) -> None:
    log = tmp_path / "f.log"
    log.write_text("[1.0] [INFO] adc: t_conv = 137 us\n", encoding="utf-8")
    events, _ = parse_text_log(log)
    measurements = extract_timing_measurements(events)
    findings = detect_timing_violations(
        measurements,
        [{"parameter": "t_conv", "min_value": "", "max_value": "",
          "unit": "us", "source": "X", "critical": False}],
    )
    assert findings == []
