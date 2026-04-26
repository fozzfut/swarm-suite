"""CLI for DocSwarm."""

from __future__ import annotations

import logging
import traceback
from pathlib import Path

import click

from . import __version__

_log = logging.getLogger("doc_swarm.cli")


@click.group()
@click.version_option(__version__, prog_name="DocSwarm")
def main():
    """DocSwarm -- Multi-agent documentation generator."""
    pass


@main.command()
@click.option("--port", default=8789, help="Port for SSE transport")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--transport", default="sse", type=click.Choice(["sse", "stdio"]))
def serve(port: int, host: str, transport: str):
    """Start the DocSwarm MCP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    from .server import create_mcp_server

    mcp = create_mcp_server()
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse", host=host, port=port)


@main.command()
@click.argument("project_path", default=".")
@click.option("--scope", default="", help="Subdirectory to scan (e.g., src/)")
@click.option("--output", "-o", default="docs", help="Output directory for generated docs")
@click.option("--verify-only", is_flag=True, help="Only verify existing docs, don't generate")
def generate(project_path: str, scope: str, output: str, verify_only: bool):
    """Generate or verify documentation for a project."""
    try:
        from .code_analyzer import CodeAnalyzer
        from .doc_generator import DocGenerator
        from .doc_verifier import DocVerifier
        from .session import SessionManager

        project = Path(project_path).resolve()
        output_dir = project / output

        click.echo(f"DocSwarm v{__version__}")
        click.echo(f"Project: {project}")
        click.echo(f"Scope: {scope or '(all)'}")
        click.echo(f"Output: {output_dir}\n")

        # Analyze code
        analyzer = CodeAnalyzer(str(project))
        modules = analyzer.scan(scope)
        click.echo(f"Scanned {len(modules)} source files")

        public = analyzer.get_public_api(modules)
        click.echo(f"Found {len(public)} modules with public API")

        undocumented = analyzer.get_undocumented(modules)
        if undocumented:
            click.echo(f"Undocumented public symbols: {len(undocumented)}")

        # Verify existing docs
        if output_dir.exists():
            verifier = DocVerifier(str(project), str(output_dir))
            issues = verifier.verify_all(modules)
            if issues:
                click.echo(f"\nVerification issues: {len(issues)}")
                for issue in issues:
                    sev = issue.severity.value.upper()
                    click.echo(f"  [{sev:8s}] {issue.title}")
                    click.echo(f"             {issue.description}")
            else:
                click.echo("\nNo verification issues found.")

            if verify_only:
                return

        # Generate docs
        mgr = SessionManager()
        session = mgr.start_session(str(project))

        gen = DocGenerator()
        pages = []

        click.echo(f"\nGenerating docs...")

        for mod_path, info in sorted(public.items()):
            page = gen.generate_api_page(mod_path, info)
            session.add_page(page)
            pages.append(page)

        # Generate index and home
        project_name = project.name
        index_page = gen.generate_index(pages)
        home_page = gen.generate_home(pages, project_name)
        documented_sources = set()
        for p in pages:
            documented_sources.update(p.source_files)
        coverage_page = gen.generate_coverage_report(
            modules, documented_sources,
        )

        session.add_page(index_page)
        session.add_page(home_page)
        session.add_page(coverage_page)
        pages.extend([index_page, home_page, coverage_page])

        # Write to disk
        written = session.write_docs(output_dir)
        click.echo(f"\nWritten {len(written)} files to {output_dir}/:")
        for w in written:
            click.echo(f"  {w}")

        click.echo(f"\nSession: {session.session_id}")
        click.echo("Done.")
    except Exception as exc:
        _log.error("Command failed: %s", exc, exc_info=True)
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)


@main.command()
@click.argument("project_path", default=".")
@click.option("--scope", default="", help="Subdirectory to scan")
def scan(project_path: str, scope: str):
    """Scan project and show code map (no generation)."""
    try:
        from .code_analyzer import CodeAnalyzer

        analyzer = CodeAnalyzer(str(Path(project_path).resolve()))
        modules = analyzer.scan(scope)

        click.echo(f"Source files: {len(modules)}\n")

        for path, info in sorted(modules.items()):
            loc = info.get("lines_of_code", 0)
            classes = info.get("classes", [])
            funcs = info.get("functions", [])
            pub_classes = [c for c in classes if c.get("is_public")]
            pub_funcs = [f for f in funcs if f.get("is_public")]

            click.echo(f"  {path} ({loc} lines)")
            for cls in pub_classes:
                methods = [m for m in cls.get("methods", []) if m.get("is_public")]
                click.echo(f"    class {cls.get('name', '?')} ({len(methods)} methods)")
            for func in pub_funcs:
                click.echo(f"    def {func.get('name', '?')}()")
    except Exception as exc:
        _log.error("Command failed: %s", exc, exc_info=True)
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)


@main.command()
@click.argument("project_path", default=".")
@click.option("--docs", default="docs", help="Docs directory to verify")
@click.option("--scope", default="", help="Code scope to check against")
def verify(project_path: str, docs: str, scope: str):
    """Verify existing docs against code."""
    try:
        from .code_analyzer import CodeAnalyzer
        from .doc_verifier import DocVerifier

        project = Path(project_path).resolve()
        docs_dir = project / docs

        if not docs_dir.exists():
            click.echo(f"Docs directory not found: {docs_dir}")
            return

        analyzer = CodeAnalyzer(str(project))
        modules = analyzer.scan(scope)

        verifier = DocVerifier(str(project), str(docs_dir))
        issues = verifier.verify_all(modules)

        if not issues:
            click.echo("All docs verified. No issues found.")
            return

        by_sev: dict[str, list] = {}
        for issue in issues:
            by_sev.setdefault(issue.severity.value, []).append(issue)

        click.echo(f"Found {len(issues)} issues:\n")
        for sev in ["critical", "high", "medium", "low", "info"]:
            sev_issues = by_sev.get(sev, [])
            if not sev_issues:
                continue
            click.echo(f"  {sev.upper()} ({len(sev_issues)}):")
            for issue in sev_issues:
                click.echo(f"    {issue.title}")
                if issue.source_file:
                    click.echo(f"      source: {issue.source_file}")
                if issue.file:
                    click.echo(f"      doc: {issue.file}")
    except Exception as exc:
        _log.error("Command failed: %s", exc, exc_info=True)
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
