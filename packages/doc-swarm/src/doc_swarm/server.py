"""MCP Server for DocSwarm -- documentation generation and verification tools."""

import json
import logging
from typing import Optional
from pathlib import Path

from .session import SessionManager
from .models import now_iso

_log = logging.getLogger("doc_swarm.server")


def create_mcp_server():
    """Create and configure the DocSwarm MCP server."""
    from mcp.server.fastmcp import FastMCP, Context
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[SessionManager]:
        mgr = SessionManager()
        yield mgr

    def _get_mgr(ctx: Optional[Context]) -> SessionManager:
        assert ctx is not None
        return ctx.request_context.lifespan_context

    mcp = FastMCP("DocSwarm", lifespan=lifespan)

    @mcp.tool(
        name="doc_generate",
        description=(
            "Generate documentation for a project. Scans source code, "
            "builds API pages, index, coverage report. Returns session info."
        ),
    )
    def _doc_generate(
        project_path: str,
        scope: str = "",
        output: str = "docs",
        ctx: Optional[Context] = None,
    ) -> str:
        from .code_analyzer import CodeAnalyzer
        from .doc_generator import DocGenerator

        mgr = _get_mgr(ctx)
        project = Path(project_path).resolve()
        output_dir = (project / output).resolve()
        if not output_dir.is_relative_to(project):
            return json.dumps({"error": "output path must be within project directory"})

        analyzer = CodeAnalyzer(str(project))
        modules = analyzer.scan(scope)
        public = analyzer.get_public_api(modules)
        undocumented = analyzer.get_undocumented(modules)

        session = mgr.start_session(str(project))
        gen = DocGenerator()
        pages = []

        for mod_path, info in sorted(public.items()):
            page = gen.generate_api_page(mod_path, info)
            session.add_page(page)
            pages.append(page)

        project_name = project.name
        index_page = gen.generate_index(pages)
        home_page = gen.generate_home(pages, project_name)
        documented_sources = set()
        for p in pages:
            documented_sources.update(p.source_files)
        coverage_page = gen.generate_coverage_report(modules, documented_sources)

        session.add_page(index_page)
        session.add_page(home_page)
        session.add_page(coverage_page)
        pages.extend([index_page, home_page, coverage_page])

        written = session.write_docs(output_dir)

        return json.dumps({
            "session_id": session.session_id,
            "scanned_files": len(modules),
            "public_modules": len(public),
            "undocumented_symbols": len(undocumented),
            "pages_generated": len(pages),
            "files_written": len(written),
            "output_dir": str(output_dir),
        })

    @mcp.tool(
        name="doc_scan",
        description="Scan project source code and return a code map (no generation).",
    )
    def _doc_scan(
        project_path: str,
        scope: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        from .code_analyzer import CodeAnalyzer

        analyzer = CodeAnalyzer(str(Path(project_path).resolve()))
        modules = analyzer.scan(scope)

        result = []
        for path, info in sorted(modules.items()):
            classes = info.get("classes", [])
            funcs = info.get("functions", [])
            result.append({
                "file": path,
                "lines": info.get("lines_of_code", 0),
                "classes": len(classes),
                "functions": len(funcs),
                "public_classes": len([c for c in classes if c.get("is_public")]),
                "public_functions": len([f for f in funcs if f.get("is_public")]),
            })

        return json.dumps({"files": len(result), "modules": result})

    @mcp.tool(
        name="doc_verify",
        description="Verify existing documentation against source code.",
    )
    def _doc_verify(
        project_path: str,
        docs_dir: str = "docs",
        scope: str = "",
        ctx: Optional[Context] = None,
    ) -> str:
        from .code_analyzer import CodeAnalyzer
        from .doc_verifier import DocVerifier

        project = Path(project_path).resolve()
        docs_path = (project / docs_dir).resolve()
        if not docs_path.is_relative_to(project):
            return json.dumps({"error": "docs_dir must be within project directory"})

        if not docs_path.exists():
            return json.dumps({"error": f"Docs directory not found: {docs_path}"})

        analyzer = CodeAnalyzer(str(project))
        modules = analyzer.scan(scope)
        verifier = DocVerifier(str(project), str(docs_path))
        issues = verifier.verify_all(modules)

        return json.dumps({
            "total_issues": len(issues),
            "issues": [
                {
                    "severity": i.severity.value,
                    "title": i.title,
                    "description": i.description,
                    "file": getattr(i, "file", ""),
                    "source_file": getattr(i, "source_file", ""),
                }
                for i in issues
            ],
        })

    @mcp.tool(
        name="doc_list_sessions",
        description="List all DocSwarm sessions.",
    )
    def _doc_list_sessions(ctx: Optional[Context] = None) -> str:
        mgr = _get_mgr(ctx)
        sessions_dir = mgr._sessions_dir
        result = []
        if sessions_dir.exists():
            for entry in sorted(sessions_dir.iterdir()):
                if entry.is_dir():
                    meta_path = entry / "meta.json"
                    if meta_path.exists():
                        try:
                            meta = json.loads(meta_path.read_text(encoding="utf-8"))
                            result.append(meta)
                        except Exception:
                            result.append({"session_id": entry.name})
        return json.dumps(result)

    return mcp
