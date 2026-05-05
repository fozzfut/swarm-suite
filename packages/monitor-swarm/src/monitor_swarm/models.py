"""Data models for trace events, timing measurements, and findings."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TraceEvent:
    """A single event extracted from a trace.

    Generic enough to represent a log line, a Saleae signal edge, or
    a protocol-decoded message. ``timestamp_us`` is microseconds from
    trace start. ``channel`` is the source ("uart0", "spi1", "log",
    "Channel 0", …). ``kind`` is parser-specific ("log", "rising",
    "falling", "transaction"). ``value`` is the raw payload (the log
    message, the byte sequence, the protocol field). ``raw_line`` is
    the original source line for traceability.
    """

    timestamp_us: float = 0.0
    channel: str = ""
    kind: str = ""
    value: str = ""
    raw_line: str = ""
    line_number: int = 0  # 1-indexed line in the source file

    def to_dict(self) -> dict:
        return {
            "timestamp_us": self.timestamp_us,
            "channel": self.channel,
            "kind": self.kind,
            "value": self.value,
            "raw_line": self.raw_line,
            "line_number": self.line_number,
        }


@dataclass
class TimingMeasurement:
    """A timing parameter extracted from one or more trace events."""

    parameter: str = ""           # e.g. "t_conv", "t_setup_spi", "ISR_duration"
    measured_us: float = 0.0      # actual measured value
    unit: str = "us"
    source_event: TraceEvent | None = None
    raw_match: str = ""           # the substring that matched

    def to_dict(self) -> dict:
        return {
            "parameter": self.parameter,
            "measured_us": self.measured_us,
            "unit": self.unit,
            "raw_match": self.raw_match,
            "source_line": self.source_event.line_number if self.source_event else 0,
            "source_timestamp_us": self.source_event.timestamp_us if self.source_event else 0.0,
        }


@dataclass
class ViolationFinding:
    """A timing constraint violation, ready to be posted to swarm-kb."""

    parameter: str = ""
    measured_us: float = 0.0
    expected_min_us: float | None = None
    expected_max_us: float | None = None
    constraint_source: str = ""    # e.g. "STM32F407 datasheet Table 47"
    severity: str = "high"          # high if exceeds max; medium otherwise
    trace_path: str = ""
    source_line: int = 0
    source_timestamp_us: float = 0.0
    raw_line: str = ""
    spec_session_id: str = ""
    component_name: str = ""

    def to_finding_dict(self) -> dict:
        """Serialise as a swarm-kb finding (compatible with FindingWriter.post)."""
        bound = []
        if self.expected_min_us is not None:
            bound.append(f">= {self.expected_min_us:g} us")
        if self.expected_max_us is not None:
            bound.append(f"<= {self.expected_max_us:g} us")
        bound_str = " AND ".join(bound) if bound else "(no bounds)"
        title = (
            f"Timing violation: {self.parameter} measured "
            f"{self.measured_us:g} us, expected {bound_str}"
        )
        suggestion = (
            "Inspect the code path that produces this timing. Check ISR "
            "priorities, DMA configuration, clock-tree settings, and any "
            "blocking calls in the relevant interrupt or driver."
        )
        return {
            "title": title,
            "severity": self.severity,
            "category": "timing-violation",
            "expert_role": "timing-analyst",
            "file": self.trace_path,
            "line_start": self.source_line,
            "line_end": self.source_line,
            "actual": (
                f"{self.parameter} = {self.measured_us:g} us at "
                f"trace t={self.source_timestamp_us:g} us "
                f"(line {self.source_line})"
            ),
            "expected": bound_str,
            "snippet": self.raw_line[:500] if self.raw_line else "",
            "source_ref": self.constraint_source,
            "suggestion_action": "investigate-timing-source",
            "suggestion_detail": suggestion,
            "confidence": 0.95,
            "tags": ["timing", "monitor"] + (
                [self.component_name] if self.component_name else []
            ),
            "status": "open",
            "_monitor": {
                "spec_session_id": self.spec_session_id,
                "component_name": self.component_name,
                "expected_min_us": self.expected_min_us,
                "expected_max_us": self.expected_max_us,
                "measured_us": self.measured_us,
            },
        }


@dataclass
class TraceAnalysisResult:
    """Output of analyzing a single trace."""

    trace_path: str = ""
    parser: str = ""               # "text_log" / "saleae_csv"
    events_parsed: int = 0
    measurements_extracted: int = 0
    findings: list[ViolationFinding] = field(default_factory=list)
    parser_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "trace_path": self.trace_path,
            "parser": self.parser,
            "events_parsed": self.events_parsed,
            "measurements_extracted": self.measurements_extracted,
            "findings_count": len(self.findings),
            "findings": [f.to_finding_dict() for f in self.findings],
            "parser_warnings": list(self.parser_warnings),
        }
