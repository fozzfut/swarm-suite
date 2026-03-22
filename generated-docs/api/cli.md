---
title: Cli
type: api
status: draft
source_files:
- src/review_swarm/cli.py
generated_by: api-mapper
verified_by: []
source_file: src/review_swarm/cli.py
lines_of_code: 454
classes: []
functions:
- main
- serve
- review
- list_sessions
- init
- report
- purge
- prompt
- tail
- stats
- export
- diff
---

# Cli

CLI entry point for ReviewSwarm.

**Source:** `src/review_swarm/cli.py` | **Lines:** 454

## Dependencies

- `__future__`
- `click`
- `collections`
- `config`
- `datetime`
- `expert_profiler`
- `json`
- `orchestrator`
- `pathlib`
- `report_generator`
- `server`
- `session_manager`
- `shutil`
- `time`

## Functions

### `def main()`

ReviewSwarm -- Collaborative AI Code Review MCP Server.

**Decorators:** `@click.group()`, `@click.version_option(__version__, prog_name='ReviewSwarm')`

**Lines:** 16-18

### `def serve(port: int, host: str, transport: str)`

Start the ReviewSwarm MCP server.

**Decorators:** `@main.command()`, `@click.option('--port', default=8787, help='Port for SSE transport')`, `@click.option('--host', default='127.0.0.1', help='Host to bind to')`, `@click.option('--transport', default='sse', type=click.Choice(['sse', 'stdio']))`

**Lines:** 25-36

### `def review(project_path: str, scope: str, task: str, max_experts: int, name: str)`

One-command review: plan and print execution instructions.

**Decorators:** `@main.command()`, `@click.argument('project_path', default='.')`, `@click.option('--scope', default='', help='File pattern or subdirectory (e.g., src/, **/*.py)')`, `@click.option('--task', default='', help='Review focus (e.g., security audit, pre-release)')`, `@click.option('--experts', 'max_experts', default=5, help='Max number of experts')`, `@click.option('--name', default='', help='Session name')`

**Lines:** 45-80

### `def list_sessions()`

List all review sessions.

**Decorators:** `@main.command('list-sessions')`

**Lines:** 84-99

### `def init(force: bool)`

Create default config at ~/.review-swarm/config.yaml.

**Decorators:** `@main.command()`, `@click.option('--force', is_flag=True, help='Overwrite existing config')`

**Lines:** 104-120

### `def report(session_id: str, fmt: str)`

Generate a report for an existing session.

**Decorators:** `@main.command()`, `@click.argument('session_id')`, `@click.option('--format', 'fmt', default='markdown', type=click.Choice(['markdown', 'json']))`

**Lines:** 126-140

### `def purge(days: int, dry_run: bool)`

Delete old completed sessions.

**Decorators:** `@main.command()`, `@click.option('--older-than', 'days', default=30, type=int, help='Delete sessions older than N days')`, `@click.option('--dry-run', is_flag=True, help='Show what would be deleted')`

**Lines:** 146-192

### `def prompt(expert_name: str | None, list_all: bool)`

Print the system prompt for an expert (for setting up AI agents).

**Decorators:** `@main.command()`, `@click.argument('expert_name', required=False)`, `@click.option('--list', 'list_all', is_flag=True, help='List available experts')`

**Lines:** 198-226

### `def tail(session_id: str, interval: float)`

Live-monitor a session's events as they happen.

**Decorators:** `@main.command()`, `@click.argument('session_id')`, `@click.option('--interval', default=2.0, help='Poll interval in seconds')`

**Lines:** 232-293

### `def stats(session_id: str | None)`

Show aggregate statistics for a session or all sessions.

**Decorators:** `@main.command()`, `@click.argument('session_id', required=False)`

**Lines:** 298-357

### `def export(session_id: str, output: str, fmt: str)`

Export a session report to a file.

**Decorators:** `@main.command()`, `@click.argument('session_id')`, `@click.option('--output', '-o', default='-', help='Output file (- for stdout)')`, `@click.option('--format', 'fmt', default='markdown', type=click.Choice(['markdown', 'json', 'sarif']))`

**Lines:** 364-388

### `def diff(session_a: str, session_b: str)`

Compare findings between two sessions.

**Decorators:** `@main.command()`, `@click.argument('session_a')`, `@click.argument('session_b')`

**Lines:** 394-450
