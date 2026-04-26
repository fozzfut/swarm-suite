"""CLAUDE.md keeper -- enforces rules-only, philosophy-first content.

Audits a CLAUDE.md file for:
    - Length (warn at 800 lines, fail at 1200).
    - Accreted bug-fix recipes (`Fixed in <commit>`, `Workaround for <issue>`,
      `## Bug:` / `## Symptom:` blocks that belong in docs/decisions/).
    - Missing required sections (Mission, Critical Rules, Architecture
      Principles, Module Boundaries, RAG Update Rule).
    - Missing pointers to docs/ subtrees.

Used by `claude_md_keeper` MCP tool and as a `kb_advance_pipeline` gate.
"""

from .audit import audit_claude_md, KeeperReport, KeeperFinding

__all__ = ["audit_claude_md", "KeeperReport", "KeeperFinding"]
