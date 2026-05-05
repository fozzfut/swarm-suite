"""Trace parsers — convert source files into TraceEvent streams."""

from .text_log import parse_text_log
from .saleae_csv import parse_saleae_csv

__all__ = ["parse_text_log", "parse_saleae_csv"]
