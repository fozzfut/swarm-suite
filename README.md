# Swarm Suite

**AI-powered multi-agent development toolkit** — six MCP tools that collaborate through a shared knowledge base to analyze specs, architect, review, fix, verify, and document your code. Built for embedded/firmware and software developers.

```
                         ┌─────────────┐
                         │   swarm-kb   │  Shared Knowledge Base
                         │  findings    │  decisions (ADR)
                         │  debates     │  pipelines
                         │  code maps   │  cross-references
                         └──────┬──────┘
        ┌───────┬───────┬───────┼───────┬───────┬───────┐
        │       │       │       │       │       │       │
   ┌────▼──┐ ┌──▼───┐ ┌─▼────┐ ┌▼────┐ ┌▼────┐ ┌▼────┐
   │ Spec  │ │ Arch │ │Review│ │Fix  │ │ Doc │ │     │
   │ Swarm │ │Swarm │ │Swarm │ │Swarm│ │Swarm│ │     │
   │hw docs│ │design│ │code  │ │patch│ │docs │ │     │
   └───────┘ └──────┘ └──────┘ └─────┘ └─────┘ └─────┘
```

## Tools

| Tool | Description | Install | Repo |
|------|-------------|---------|------|
| **[swarm-kb](https://github.com/fozzfut/swarm-kb)** | Shared knowledge base — findings, decisions, debates, pipelines, code maps | `pip install swarm-kb` | [repo](https://github.com/fozzfut/swarm-kb) |
| **[SpecSwarm](https://github.com/fozzfut/spec-swarm)** | Hardware spec analyzer — datasheets, register maps, CAN/SPI/I2C/EtherCAT/Modbus/OPC UA | `pip install spec-swarm-ai` | [repo](https://github.com/fozzfut/spec-swarm) |
| **[ArchSwarm](https://github.com/fozzfut/arch-swarm)** | Multi-agent architecture debates — coupling, modularity, scalability analysis | `pip install arch-swarm-ai` | [repo](https://github.com/fozzfut/arch-swarm) |
| **[ReviewSwarm](https://github.com/fozzfut/review-swarm)** | Multi-agent code review — 13 experts (security, performance, threading, etc.) | `pip install review-swarm` | [repo](https://github.com/fozzfut/review-swarm) |
| **[FixSwarm](https://github.com/fozzfut/fix-swarm)** | Multi-agent code fixer — propose, review, consensus, apply, verify | `pip install fix-swarm-ai` | [repo](https://github.com/fozzfut/fix-swarm) |
| **[DocSwarm](https://github.com/fozzfut/doc-swarm)** | Documentation generator — API docs, verification, maintenance | `pip install doc-swarm-ai` | [repo](https://github.com/fozzfut/doc-swarm) |

## Quick Start

### Install

```bash
# Full suite
pip install swarm-kb review-swarm doc-swarm-ai fix-swarm-ai arch-swarm-ai spec-swarm-ai

# With PDF support for datasheets
pip install spec-swarm-ai[pdf]
```

### Add MCP servers (Claude Code)

```bash
claude mcp add swarm-kb     -- swarm-kb serve --transport stdio
claude mcp add spec-swarm   -- spec-swarm serve --transport stdio
claude mcp add arch-swarm   -- arch-swarm serve --transport stdio
claude mcp add review-swarm -- review-swarm serve --transport stdio
claude mcp add fix-swarm    -- fix-swarm serve --transport stdio
claude mcp add doc-swarm    -- doc-swarm serve --transport stdio
```

### Add MCP servers (Cursor / Windsurf / Cline)

```json
{
  "mcpServers": {
    "swarm-kb":     { "url": "http://localhost:8788/sse" },
    "spec-swarm":   { "url": "http://localhost:8769/sse" },
    "arch-swarm":   { "url": "http://localhost:8768/sse" },
    "review-swarm": { "url": "http://localhost:8765/sse" },
    "fix-swarm":    { "url": "http://localhost:8767/sse" },
    "doc-swarm":    { "url": "http://localhost:8766/sse" }
  }
}
```

## Pipeline Workflow

The suite follows a defined pipeline with **user gates** between stages. You control the pace — no automatic progression.

### For embedded/hardware projects

```
kb_start_pipeline("./project", include_spec=True)
```

```
Stage 0: Spec Analysis (SpecSwarm)
  ├── Ingest datasheets, reference manuals
  ├── Extract: registers, pins, protocols, timing, power, memory
  ├── Check conflicts: pin collisions, bus overload, power budget
  └── Export constraints to swarm-kb
  USER GATE: review specs → kb_advance_pipeline()

Stage 1: Architecture Analysis (ArchSwarm)
  ├── Scan project metrics: coupling, complexity, dependencies
  ├── Multi-agent debates on design decisions (real AI analysis)
  ├── Decisions become ADRs in swarm-kb
  └── Hardware constraints from Stage 0 inform architecture
  USER GATE: review findings → kb_advance_pipeline()

Stage 2: Code Review (ReviewSwarm)
  ├── 13 experts review code (security, performance, threading, etc.)
  ├── Experts receive ADRs as context — flag violations
  ├── Cross-check phase: experts react to each other's findings
  └── Decision compliance check
  USER GATE: review findings → kb_advance_pipeline()

Stage 3: Fix (FixSwarm)
  ├── snapshot_tests() — save baseline
  ├── Fix experts propose changes with consensus
  ├── Cross-review: experts approve/reject each other's fixes
  └── apply_approved() — only consensus fixes applied
  USER GATE: review fixes → kb_advance_pipeline()

Stage 4: Regression Check (FixSwarm)
  ├── Syntax validation on modified files
  ├── Test suite comparison (before vs after)
  └── Re-scan for new issues
  USER GATE: verify clean → kb_advance_pipeline()

Stage 5: Documentation (DocSwarm)
  ├── Verify existing docs against changed code
  └── Generate/update API documentation
  → Pipeline complete!
```

### For software projects

```
kb_start_pipeline("./project")
```

Starts at Stage 1 (architecture), skipping spec analysis.

## Architecture

All tools communicate via **MCP (Model Context Protocol)** through a shared knowledge base:

```
SpecSwarm ──► kb_post_finding(hw constraints) ──► ArchSwarm reads constraints
ArchSwarm ──► kb_post_decision(ADR) ──────────► ReviewSwarm checks compliance
         ──► kb_start_debate / kb_resolve ────► decisions available to all
ReviewSwarm → kb_post_finding(code issues) ───► FixSwarm reads findings
FixSwarm ──► kb_post_xref(finding → fix) ─────► traceable fix chain
```

**Key principle:** No tool imports another. All data flows through swarm-kb. Each tool works independently if swarm-kb is unavailable.

### Debates

Any tool can start a debate when agents disagree:

```
kb_start_debate(topic="...", source_tool="review")
kb_propose(debate_id, author="Security Expert", ...)
kb_critique(debate_id, proposal_id, critic="Performance Expert", ...)
kb_vote(debate_id, agent="...", proposal_id="...", support=True)
kb_resolve_debate(debate_id) → ADR saved automatically
```

## Expert Profiles

| Tool | Experts | Focus |
|------|---------|-------|
| **SpecSwarm** | 9 | MCU peripherals, CAN/CANopen/EtherCAT/PROFINET/Modbus, power, sensors, motors, memory, timing, safety |
| **ArchSwarm** | 10 | Simplicity, modularity, reuse, scalability, trade-offs, API design, data modeling, testing strategy, dependencies, observability |
| **ReviewSwarm** | 13 | Security, performance, threading, error handling, API contracts, consistency, dead code, dependencies, logging, resources, tests, types, project context |
| **FixSwarm** | 8 | Refactoring, security fix, performance fix, type fix, error handling fix, test fix, dependency fix, compatibility fix |
| **DocSwarm** | 8 | API reference, tutorials, changelog, migration guides, architecture docs, inline docs, README quality, error messages |

**Total: 48 expert profiles** — all language-agnostic, customizable via YAML.

## Requirements

- Python 3.10+
- An MCP-compatible AI client (Claude Code, Cursor, Windsurf, Cline, etc.)
- For PDF datasheets: `pip install spec-swarm-ai[pdf]`

## License

MIT — [Ilya Sidorov](https://github.com/fozzfut)
