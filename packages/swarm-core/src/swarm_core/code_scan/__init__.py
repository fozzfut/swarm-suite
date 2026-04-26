"""Static analysis of project structure -- coupling, complexity, dep graph.

This is the canonical home for the AST-based scanner. Both `arch_swarm`
(architecture analysis) and `fix_swarm` (arch-aware fix proposals)
consume this module instead of importing from each other -- which would
violate the layering rule (no `*-swarm <-> *-swarm` imports).

History: lived in `arch_swarm.code_scanner` until 2026-04-26; extracted
to `swarm_core.code_scan` so fix-swarm can use it without crossing the
tool boundary. See `docs/decisions/2026-04-26-fix-swarm-arch-coupling.md`.
"""

from .scanner import (
    ModuleInfo,
    CouplingMetrics,
    ArchAnalysis,
    scan_project,
    format_analysis,
)

__all__ = ["ModuleInfo", "CouplingMetrics", "ArchAnalysis", "scan_project", "format_analysis"]
