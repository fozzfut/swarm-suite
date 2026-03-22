"""MCP Server for the Swarm knowledge base -- cross-tool tools."""

import json
import logging
from typing import Optional

from .bootstrap import bootstrap
from .config import SuiteConfig
from .code_map.scanner import scan_project
from .code_map.store import CodeMapStore
from .finding_reader import search_all_findings, get_finding_reader
from .paths import code_map_path, project_hash_for
from .session_meta import count_sessions, list_sessions
from .xref import XRefLog

_log = logging.getLogger("swarm_kb.server")


def create_mcp_server():
    """Create and configure the swarm-kb MCP server."""
    from mcp.server.fastmcp import FastMCP, Context
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[SuiteConfig]:
        config = bootstrap()
        yield config

    def _get_config(ctx: Optional[Context]) -> SuiteConfig:
        assert ctx is not None, "MCP Context not injected"
        return ctx.request_context.lifespan_context

    mcp = FastMCP("SwarmKB", lifespan=lifespan)

    # ── kb_status ────────────────────────────────────────────────────

    @mcp.tool(
        name="kb_status",
        description=(
            "Get Swarm KB status: session counts per tool, "
            "cross-reference count, storage root path."
        ),
    )
    def _kb_status(ctx: Optional[Context] = None) -> str:
        config = _get_config(ctx)
        counts = count_sessions(config)
        xref_log = XRefLog(config.xrefs_path)
        return json.dumps({
            "kb_root": str(config.kb_root),
            "sessions": counts,
            "total_sessions": sum(counts.values()),
            "xrefs": xref_log.count(),
        }, indent=2)

    # ── kb_scan_project ──────────────────────────────────────────────

    @mcp.tool(
        name="kb_scan_project",
        description=(
            "Scan a project and update its code map. "
            "Returns summary of scanned modules, coupling, complexity. "
            "Use force=true to rescan even if cache is fresh."
        ),
    )
    def _kb_scan_project(
        project_path: str,
        scope: str = "",
        force: bool = False,
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        cm_path = code_map_path(project_path, config)
        store = CodeMapStore(cm_path)

        if not force and store.is_fresh(config.code_map.cache_ttl_hours):
            existing = store.load()
            if existing:
                return json.dumps({
                    "status": "cached",
                    "scanned_at": existing.scanned_at,
                    "total_modules": existing.total_modules,
                    "total_lines": existing.total_lines,
                })

        skip_dirs = set(config.code_map.skip_dirs)
        source_exts = set(config.code_map.source_exts)
        max_size = int(config.code_map.max_file_size_mb * 1024 * 1024)

        code_map = scan_project(
            project_path, scope=scope,
            skip_dirs=skip_dirs, source_exts=source_exts,
            max_file_size=max_size,
        )
        store.save(code_map)

        return json.dumps({
            "status": "scanned",
            "scanned_at": code_map.scanned_at,
            "total_modules": code_map.total_modules,
            "total_lines": code_map.total_lines,
            "coupling_count": len(code_map.coupling),
        })

    # ── kb_get_code_map ──────────────────────────────────────────────

    @mcp.tool(
        name="kb_get_code_map",
        description=(
            "Get the cached code map for a project. "
            "Returns modules, dependency graph, coupling metrics, complexity. "
            "Run kb_scan_project first if no cache exists."
        ),
    )
    def _kb_get_code_map(
        project_path: str,
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        cm_path = code_map_path(project_path, config)
        store = CodeMapStore(cm_path)
        code_map = store.load()

        if code_map is None:
            return json.dumps({"error": "No code map found. Run kb_scan_project first."})

        return json.dumps(code_map.to_dict())

    # ── kb_list_sessions ─────────────────────────────────────────────

    @mcp.tool(
        name="kb_list_sessions",
        description=(
            "List sessions across all tools (or filter by tool). "
            "Returns session IDs, status, timestamps."
        ),
    )
    def _kb_list_sessions(
        tool: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        sessions = list_sessions(config, tool=tool or None)
        return json.dumps(sessions, default=str)

    # ── kb_get_xrefs ─────────────────────────────────────────────────

    @mcp.tool(
        name="kb_get_xrefs",
        description=(
            "Get cross-tool references. Filter by source_tool, target_tool, "
            "source_session, target_session, target_entity_id, relation."
        ),
    )
    def _kb_get_xrefs(
        source_tool: str = "",
        target_tool: str = "",
        source_session: str = "",
        target_session: str = "",
        target_entity_id: str = "",
        relation: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        xref_log = XRefLog(config.xrefs_path)
        xrefs = xref_log.query(
            source_tool=source_tool or None,
            target_tool=target_tool or None,
            source_session=source_session or None,
            target_session=target_session or None,
            target_entity_id=target_entity_id or None,
            relation=relation or None,
        )
        return json.dumps([x.to_dict() for x in xrefs])

    # ── kb_post_xref ─────────────────────────────────────────────────

    @mcp.tool(
        name="kb_post_xref",
        description=(
            "Create a cross-reference between sessions/entities. "
            "Relations: fixes, documents, addresses, informed_by."
        ),
    )
    def _kb_post_xref(
        source_tool: str,
        source_session: str,
        source_entity_id: str,
        target_tool: str,
        target_session: str,
        target_entity_id: str,
        relation: str,
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        xref_log = XRefLog(config.xrefs_path)
        xref = xref_log.append(
            source_tool=source_tool,
            source_session=source_session,
            source_entity_id=source_entity_id,
            target_tool=target_tool,
            target_session=target_session,
            target_entity_id=target_entity_id,
            relation=relation,
        )
        return json.dumps(xref.to_dict())

    # ── kb_search_findings ───────────────────────────────────────────

    @mcp.tool(
        name="kb_search_findings",
        description=(
            "Search findings across all review sessions. "
            "Filter by file, severity, status, min_confidence."
        ),
    )
    def _kb_search_findings(
        file: str = "",
        severity: str = "",
        status: str = "",
        min_confidence: float = 0.0,
        ctx: Optional[Context] = None,
    ) -> str:
        config = _get_config(ctx)
        results = search_all_findings(
            config,
            file=file or None,
            severity=severity or None,
            status=status or None,
            min_confidence=min_confidence if min_confidence > 0 else None,
        )
        return json.dumps(results)

    # ── kb_migrate ───────────────────────────────────────────────────

    @mcp.tool(
        name="kb_migrate",
        description=(
            "Manually trigger migration from legacy storage paths "
            "(~/.review-swarm, ~/.doc-swarm) to the shared KB. "
            "Idempotent -- skips already-migrated sessions."
        ),
    )
    def _kb_migrate(ctx: Optional[Context] = None) -> str:
        from .compat import migrate_all
        config = _get_config(ctx)
        result = migrate_all(config)
        total = sum(len(v) for v in result.values())
        return json.dumps({
            "migrated": result,
            "total": total,
        })

    return mcp
