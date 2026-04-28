# swarm-kb

> **Part of [Swarm Suite](https://github.com/fozzfut/swarm-suite).** Most users install the whole suite and drive it through the [main README](../../README.md) and `/swarm-*` slash commands — they never read this file. This README documents the package itself for contributors and standalone users.

**Shared knowledge base + coordination layer** for the Swarm Suite. Stores findings, decisions, debates, judgings, verifications, PGVE (Planner-Generator-Evaluator) sessions, flow definitions, pipelines, and code maps under `~/.swarm-kb/`. Every other Swarm Suite tool talks to this package — they never talk to each other.

Also home to the user-facing pipeline tools that don't fit any single tool's domain: Idea (Stage 0a), Plan (Stage 2), Hardening (Stage 7), Release (Stage 8), the navigator, the CLAUDE.md keeper, and the lite-mode escape hatches (`kb_quick_review`, `kb_quick_fix`).

## Install

```bash
pip install swarm-kb
```

## Connect to your AI client

```bash
# Claude Code (built and tested)
claude mcp add swarm-kb -- swarm-kb serve --transport stdio
```

For Cursor / Windsurf / Cline (untested but should work via MCP), see the main [README § Connect to your AI client](../../README.md#connect-to-your-ai-client).

## CLI

```bash
swarm-kb status                          # Show KB health: session counts, storage root
swarm-kb serve --transport stdio         # MCP server (stdio for Claude Code)
swarm-kb serve --port 8788               # MCP server (SSE for Cursor / Windsurf / Cline)
```

## Storage layout

```
~/.swarm-kb/
├── arch/sessions/        # arch-swarm sessions
├── review/sessions/      # review-swarm sessions
├── fix/sessions/         # fix-swarm sessions
├── doc/sessions/         # doc-swarm sessions
├── spec/sessions/        # spec-swarm sessions (embedded only)
├── idea/sessions/        # Stage 0a: Idea sessions
├── plan/sessions/        # Stage 2: Plan sessions
├── harden/sessions/      # Stage 7: Hardening sessions
├── release/sessions/     # Stage 8: Release prep sessions
├── debates/              # cross-tool debate sessions (13 formats)
├── decisions/            # ADRs (Architecture Decision Records)
├── pipelines/            # pipeline state — current stage, gates, sessions
├── code-map/             # AST-based code analysis per project
├── xrefs/                # cross-tool references (finding → fix → doc)
├── logs/                 # rotating per-tool log files
├── config.yaml           # suite-wide config
└── quality_gate.json     # quality-gate thresholds (max_critical, max_high, …)
```

All event streams (`findings.jsonl`, `reactions.jsonl`, `events.jsonl`, `messages.jsonl`) are append-only. Single-writer files (`meta.json`, claims) use atomic write (tempfile + os.replace) under cross-process file locks. Sessions are durable across server restarts — restarting the MCP server reproduces the same view.

## Migration from legacy tool-specific dirs

On first startup, swarm-kb automatically migrates legacy directories:

- `~/.review-swarm/` → `~/.swarm-kb/review/sessions/`
- `~/.doc-swarm/` → `~/.swarm-kb/doc/sessions/`
- `.archswarm_sessions/` → `~/.swarm-kb/arch/sessions/`

If you upgraded from pre-suite versions, run `swarm-kb status` to confirm the migration ran.

## Suite overview

Universal Python tooling (run by default):

| Tool | Package | Purpose |
|------|---------|---------|
| **swarm-core** | `swarmsuite-core` | Shared foundation — runtime dep of everything below |
| **swarm-kb** | `swarm-kb` | This package — KB + coordination + Idea/Plan/Hardening/Release |
| **arch-swarm** | `arch-swarm-ai` | Architecture analysis & multi-agent debate |
| **review-swarm** | `review-swarm` | Multi-expert code review |
| **fix-swarm** | `fix-swarm-ai` | Fix proposal + consensus + apply |
| **doc-swarm** | `doc-swarm-ai` | Documentation generation + verification |

Optional add-on for embedded / industrial projects:

| Tool | Package | Purpose |
|------|---------|---------|
| **spec-swarm** | `spec-swarm-ai` | Hardware spec analyzer (datasheets, registers, fieldbuses) |

Install the full suite:

```bash
pip install swarmsuite-core swarm-kb arch-swarm-ai review-swarm fix-swarm-ai doc-swarm-ai
pip install spec-swarm-ai     # embedded only
```

## License

MIT — [Ilya Sidorov](https://github.com/fozzfut)
