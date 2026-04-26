"""Compatibility shim -- the scanner moved to swarm_core.code_scan.

This module re-exports the public surface for any external caller still
importing `arch_swarm.code_scanner`. New code should import from
`swarm_core.code_scan` directly.

Migration: 2026-04-26. See docs/decisions/2026-04-26-fix-swarm-arch-coupling.md.
"""

from swarm_core.code_scan import (
    ModuleInfo,
    CouplingMetrics,
    ArchAnalysis,
    scan_project,
    format_analysis,
)

__all__ = ["ModuleInfo", "CouplingMetrics", "ArchAnalysis", "scan_project", "format_analysis"]
