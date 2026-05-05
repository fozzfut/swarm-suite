"""CLI entry point for swarm-kb."""

from __future__ import annotations

import json
import logging

import click

from swarm_core.logging_setup import setup_logging

from . import __version__
from .config import SuiteConfig

_log = logging.getLogger("swarm_kb.migrate_per_project")


@click.group()
@click.version_option(__version__, prog_name="swarm-kb")
def main():
    """SwarmKB -- Shared knowledge base for the Swarm suite."""
    pass


@main.command()
@click.option("--port", default=8788, help="Port for SSE transport")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--transport", default="sse", type=click.Choice(["sse", "stdio"]))
def serve(port: int, host: str, transport: str):
    """Start the SwarmKB MCP server.

    On startup, automatically initializes directories and migrates
    legacy data from ~/.review-swarm, ~/.doc-swarm, etc.
    """
    setup_logging("kb")

    from .server import create_mcp_server

    mcp = create_mcp_server()

    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse", host=host, port=port)


@main.command()
def status():
    """Show KB status: session counts, storage root, xref count."""
    setup_logging("kb")

    config = SuiteConfig.load()

    from .bootstrap import bootstrap
    config = bootstrap(config)

    from .session_meta import count_sessions
    from .xref import XRefLog

    counts = count_sessions(config)
    xref_log = XRefLog(config.xrefs_path)

    click.echo(f"SwarmKB v{__version__}")
    click.echo(f"Storage: {config.kb_root}")
    click.echo(f"Config:  {config.config_file}")
    click.echo()
    click.echo("Sessions:")
    total = 0
    for tool, count in sorted(counts.items()):
        click.echo(f"  {tool:>8s}: {count}")
        total += count
    click.echo(f"  {'total':>8s}: {total}")
    click.echo(f"\nCross-references: {xref_log.count()}")


@main.command()
def migrate():
    """Migrate sessions from legacy storage paths to the shared KB."""
    setup_logging("kb")

    config = SuiteConfig.load()

    from .bootstrap import _ensure_dirs
    from .compat import migrate_all

    _ensure_dirs(config)
    result = migrate_all(config)

    total = sum(len(v) for v in result.values())
    if total:
        click.echo(f"Migrated {total} session(s):")
        for tool, ids in result.items():
            for sid in ids:
                click.echo(f"  [{tool}] {sid}")
    else:
        click.echo("No sessions to migrate.")


@main.command(name="vector-rebuild")
@click.option(
    "--scope",
    default="all",
    help="all | findings | decisions | tool:<name>",
)
def vector_rebuild(scope: str):
    """Rebuild the semantic vector index from existing JSONL files.

    Idempotent: entries whose text hash matches the indexed version
    are skipped (metadata still refreshed). Use after enabling the
    embedding provider for the first time, after editing JSONL by
    hand, or when changing the embedding model.
    """
    setup_logging("kb")

    config = SuiteConfig.load()

    from .vector_index import VectorIndex, make_embedder

    embedder = make_embedder({
        "provider": config.embedding.provider,
        "model": config.embedding.model,
    })
    if embedder is None:
        click.echo(
            "Embedding provider not configured. Edit "
            f"{config.config_file}:\n"
            "  embedding:\n"
            "    provider: local\n"
            "    model: intfloat/multilingual-e5-small\n"
            "and `pip install swarm-kb[embed-local]`.",
            err=True,
        )
        raise click.Abort()

    vector_idx = VectorIndex(config.vector_index_path, embedder=embedder)
    try:
        stats = vector_idx.rebuild_from_jsonl(config, scope=scope)
    finally:
        vector_idx.close()

    click.echo(f"Rebuild scope: {scope}")
    click.echo(f"  indexed: {stats.indexed}")
    click.echo(f"  skipped: {stats.skipped}")
    click.echo(f"  errors:  {stats.errors}")
    if stats.by_type:
        click.echo("  by_type:")
        for k, v in stats.by_type.items():
            click.echo(f"    {k}: {v}")


@main.command(name="migrate-to-per-project")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would happen, don't move anything.",
)
@click.option(
    "--keep-legacy",
    is_flag=True,
    default=False,
    help="Copy instead of move; legacy global paths stay in place.",
)
@click.option(
    "--default-project",
    default=None,
    type=str,
    help=(
        "project_path used as the bucket for entries without a project_path "
        "field. If omitted, unattributed entries are grouped under a "
        "synthetic '_legacy_unattributed' project."
    ),
)
@click.option(
    "--finalize",
    is_flag=True,
    default=False,
    help=(
        "Delete legacy global paths after a successful migration. Run this "
        "only after verifying the per-project layout looks correct."
    ),
)
def migrate_to_per_project(
    dry_run: bool,
    keep_legacy: bool,
    default_project: str | None,
    finalize: bool,
):
    """Migrate legacy global swarm-kb storage to the per-project layout.

    Phase 5 introduces per-project isolation under
    ``~/.swarm-kb/projects/<project_hash>/`` so findings, decisions,
    debates, pipelines, and the vector index don't leak across unrelated
    projects. This command moves (or copies, with --keep-legacy) all
    legacy global state into the new layout.

    The legacy global vector index at ``index/kb.db`` is dropped --
    rebuild per project afterwards with::

        swarm-kb vector-rebuild --project /path/to/project
    """
    setup_logging("kb")

    config = SuiteConfig.load()

    from .migrate_per_project import cleanup_legacy, run_migration

    if finalize:
        deleted = cleanup_legacy(config, dry_run=dry_run)
        prefix = "[dry-run] would delete" if dry_run else "Deleted"
        if deleted:
            click.echo(f"{prefix} {len(deleted)} legacy path(s):")
            for p in deleted:
                click.echo(f"  {p}")
        else:
            click.echo("No legacy paths to delete.")
        return

    result = run_migration(
        config,
        dry_run=dry_run,
        keep_legacy=keep_legacy,
        default_project=default_project,
    )

    if dry_run:
        click.echo("[dry-run] no files were moved or written.")
        click.echo()

    click.echo("Migration summary:")
    click.echo(
        f"  sessions migrated:        {result.sessions_migrated}"
        f" (across {len(result.sessions_by_project)} project(s))"
    )
    click.echo(f"  decisions migrated:       {result.decisions_migrated}")
    click.echo(
        f"  debates migrated:         {result.debates_migrated}"
        f" ({result.debate_dirs_migrated} active debate dir(s))"
    )
    click.echo(f"  pipelines migrated:       {result.pipelines_migrated}")
    click.echo(f"  code-maps migrated:       {result.code_maps_migrated}")
    if result.vector_index_dropped:
        if keep_legacy:
            note = "renamed to .bak (run `swarm-kb vector-rebuild` per project)"
        else:
            note = "dropped (run `swarm-kb vector-rebuild` per project)"
        click.echo(f"  legacy vector index:      {note}")
    else:
        click.echo("  legacy vector index:      (none found)")

    if result.projects:
        click.echo()
        click.echo("Migrated projects:")
        for project_hash, project_label in sorted(result.projects.items()):
            short = project_hash[:8]
            click.echo(f"  {short}  ->  {project_label}")

    if result.skipped:
        click.echo()
        click.echo(f"Skipped {len(result.skipped)} item(s) (already migrated):")
        for line in result.skipped[:10]:
            click.echo(f"  {line}")
        if len(result.skipped) > 10:
            click.echo(f"  ... and {len(result.skipped) - 10} more")

    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Verify per-project layout: ls ~/.swarm-kb/projects/")
    click.echo("  2. For each project, rebuild the vector index:")
    click.echo("       swarm-kb vector-rebuild --project /path/to/project")
    if not keep_legacy and not dry_run:
        click.echo("  3. (Optional) After validation, delete legacy paths with:")
        click.echo("       swarm-kb migrate-to-per-project --finalize")


if __name__ == "__main__":
    main()
