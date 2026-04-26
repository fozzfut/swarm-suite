# swarm-kb

Shared knowledge base for the Swarm AI suite: [ReviewSwarm](https://github.com/fozzfut/review-swarm), FixSwarm, DocSwarm, ArchSwarm.

Provides centralized session storage, cross-tool references, and code mapping so all swarm tools share a single knowledge layer at `~/.swarm-kb/`.

## Installation

```bash
pip install swarm-kb
```

## MCP Server Setup

### Claude Code

```bash
claude mcp add swarm-kb -- swarm-kb serve --transport stdio
```

### Cursor / Windsurf / Cline (SSE)

```bash
swarm-kb serve --port 8788
```

Then add to your MCP config:

```json
{
  "mcpServers": {
    "swarm-kb": {
      "url": "http://localhost:8788/sse"
    }
  }
}
```

### Manual `.mcp.json` (per-project)

```json
{
  "mcpServers": {
    "swarm-kb": {
      "type": "stdio",
      "command": "swarm-kb",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

## CLI

```bash
swarm-kb status          # Show KB health: session counts, storage root
swarm-kb serve           # Start MCP server (SSE on port 8788)
swarm-kb serve --transport stdio  # Start MCP server (stdio for Claude Code)
```

## Storage Layout

```
~/.swarm-kb/
├── sessions/
│   ├── review/     # ReviewSwarm sessions
│   ├── doc/        # DocSwarm sessions
│   ├── arch/       # ArchSwarm sessions
│   └── fix/        # FixSwarm sessions
├── code-maps/      # AST-based code analysis per project
└── xrefs.jsonl     # Cross-tool references
```

## Migration

On first startup, swarm-kb automatically migrates data from legacy tool-specific directories:

- `~/.review-swarm/` -> `~/.swarm-kb/sessions/review/`
- `~/.doc-swarm/` -> `~/.swarm-kb/sessions/doc/`
- `.archswarm_sessions/` -> `~/.swarm-kb/sessions/arch/`

## Suite Overview

| Tool | Package | Purpose |
|------|---------|---------|
| **swarm-kb** | `swarm-kb` | Shared knowledge base & code maps |
| **ReviewSwarm** | `review-swarm` | Collaborative AI code review |
| **DocSwarm** | `doc-swarm-ai` | Documentation generation |
| **FixSwarm** | `fix-swarm-ai` | Automated fix planning & application |
| **ArchSwarm** | `arch-swarm-ai` | Architecture analysis & debate |

Install the full suite:

```bash
pip install swarm-kb review-swarm doc-swarm-ai fix-swarm-ai arch-swarm-ai
```

## License

MIT
