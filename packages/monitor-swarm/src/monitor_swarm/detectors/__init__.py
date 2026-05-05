"""Detectors — analyse TraceEvent streams against spec constraints."""

from .timing_violation import detect_timing_violations, extract_timing_measurements

__all__ = ["detect_timing_violations", "extract_timing_measurements"]
