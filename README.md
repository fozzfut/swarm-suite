# Swarm Suite

**AI-powered multi-agent development toolkit** — five MCP tools that collaborate through a shared knowledge base to review, document, fix, and architect your code.

```
                    ┌─────────────┐
                    │   swarm-kb   │  Shared Knowledge Base
                    │  code maps   │  cross-tool references
                    │  sessions    │  centralized storage
                    └──────┬──────┘
           ┌───────┬───────┼───────┬───────┐
           │       │       │       │       │
      ┌────▼──┐ ┌──▼───┐ ┌▼────┐ ┌▼────┐  │
      │Review │ │ Doc  │ │Fix  │ │Arch │  │
      │Swarm  │ │Swarm │ │Swarm│ │Swarm│  │
      └───────┘ └──────┘ └─────┘ └─────┘  │
```

## Tools

| Tool | Description | Install | Repo |
|------|-------------|---------|------|
| **[swarm-kb](https://github.com/fozzfut/swarm-kb)** | Shared knowledge base — code maps, cross-tool references, centralized session storage | `pip install swarm-kb` | [repo](https://github.com/fozzfut/swarm-kb) |
| **[ReviewSwarm](https://github.com/fozzfut/review-swarm)** | Collaborative multi-agent code review with expert profiles (security, performance, error handling, etc.) | `pip install review-swarm` | [repo](https://github.com/fozzfut/review-swarm) |
| **[DocSwarm](https://github.com/fozzfut/doc-swarm)** | Multi-agent documentation generation, verification, and maintenance | `pip install doc-swarm-ai` | [repo](https://github.com/fozzfut/doc-swarm) |
| **[FixSwarm](https://github.com/fozzfut/fix-swarm)** | Reads review reports and generates targeted code fixes | `pip install fix-swarm-ai` | [repo](https://github.com/fozzfut/fix-swarm) |
| **[ArchSwarm](https://github.com/fozzfut/arch-swarm)** | Multi-agent architecture debates for simplicity, modularity, and reusability | `pip install arch-swarm-ai` | [repo](https://github.com/fozzfut/arch-swarm) |

## Quick Start

### Install the full suite

```bash
pip install swarm-kb review-swarm doc-swarm-ai fix-swarm-ai arch-swarm-ai
```

### Add MCP servers (Claude Code)

```bash
claude mcp add swarm-kb     -- swarm-kb serve --transport stdio
claude mcp add review-swarm -- review-swarm serve --transport stdio
claude mcp add doc-swarm    -- doc-swarm serve --transport stdio
claude mcp add fix-swarm    -- fix-swarm serve --transport stdio
claude mcp add arch-swarm   -- arch-swarm serve --transport stdio
```

### Add MCP servers (Cursor / Windsurf / Cline)

Start each server on its own port:

```bash
swarm-kb serve --port 8788
review-swarm serve --port 8765
doc-swarm serve --port 8766
fix-swarm serve --port 8767
arch-swarm serve --port 8768
```

Then add to your MCP config:

```json
{
  "mcpServers": {
    "swarm-kb":     { "url": "http://localhost:8788/sse" },
    "review-swarm": { "url": "http://localhost:8765/sse" },
    "doc-swarm":    { "url": "http://localhost:8766/sse" },
    "fix-swarm":    { "url": "http://localhost:8767/sse" },
    "arch-swarm":   { "url": "http://localhost:8768/sse" }
  }
}
```

## Workflow

The tools are designed to work together in a natural development cycle:

1. **ReviewSwarm** scans your code and produces findings with severity, location, and expert context
2. **FixSwarm** reads ReviewSwarm reports and generates targeted fixes
3. **DocSwarm** generates and maintains documentation based on the current codebase
4. **ArchSwarm** debates architectural decisions when design trade-offs need discussion
5. **swarm-kb** ties everything together — shared sessions, cross-references, and code maps

```
Code change → ReviewSwarm (find issues) → FixSwarm (apply fixes) → ReviewSwarm (verify)
                                        ↘ DocSwarm (update docs)
                                        ↘ ArchSwarm (debate design)
```

## Architecture

All tools communicate via **MCP (Model Context Protocol)** — they expose tools that AI agents call directly. There is no orchestrator process; the AI model coordinates the workflow.

**swarm-kb** provides the shared data layer:
- **Sessions** — each tool stores review/doc/fix/arch sessions in `~/.swarm-kb/sessions/`
- **Code maps** — AST-based analysis of project structure
- **Cross-references** — links between findings across tools (e.g., a ReviewSwarm finding linked to a FixSwarm fix)

## Requirements

- Python 3.10+
- An MCP-compatible AI client (Claude Code, Cursor, Windsurf, Cline, etc.)

## License

MIT — [Ilya Sidorov](https://github.com/fozzfut)
