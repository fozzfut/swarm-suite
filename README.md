# Swarm Suite

**Take a Python project from idea to production-grade industrial code.** Seven MCP tools that collaborate through a shared knowledge base to capture ideas, analyze specs, architect, plan, review, fix, document, harden, and release your code -- enforcing **SOLID + DRY** at every stage.

> Built for Python first; embedded C supported via SpecSwarm for hardware spec extraction. Other languages best-effort.

```
                          +----------------+
                          |  swarm-core   |   shared foundation:
                          |  models       |     models, ExpertRegistry,
                          |  experts      |     SessionLifecycle,
                          |  coordination |     MessageBus / EventBus /
                          |  mcp / keeper |     PhaseBarrier / RateLimiter,
                          +-------+-------+     MCPApp, CLAUDE.md keeper
                                  |
                          +-------v-------+
                          |   swarm-kb    |   storage layer:
                          |  findings     |     findings, decisions,
                          |  decisions    |     debates, pipelines,
                          |  debates      |     code maps, cross-refs,
                          |  pipelines    |     quality gate state
                          +---+---+---+--+
        +-----+-----+-----+---|---|---|----+-----+-----+
        |     |     |     |   |   |   |    |     |     |
        v     v     v     v                v     v     v
      Spec  Arch  Plan  Review  Fix  Doc  Hard  Release
      Swarm Swarm (NEW) Swarm   Swarm Swarm (NEW)(NEW)
                                                  ^
                              "Idea -> Production" pipeline
```

## Packages

| Package | Description | Install |
|---------|-------------|---------|
| **swarm-core**   | Shared foundation: models, expert registry, session lifecycle, coordination primitives, MCP scaffolding, CLAUDE.md keeper | `pip install swarm-core` |
| **swarm-kb**     | Shared knowledge base -- findings, decisions, debates, pipelines, code maps | `pip install swarm-kb` |
| **SpecSwarm**    | Hardware spec analyzer -- datasheets, register maps, CAN/SPI/I2C/EtherCAT/Modbus/OPC UA | `pip install spec-swarm-ai` |
| **ArchSwarm**    | Multi-agent architecture debates -- coupling, modularity, scalability, SOLID-grounded designs | `pip install arch-swarm-ai` |
| **ReviewSwarm**  | Multi-agent code review -- 13 experts (security, performance, threading, SOLID/DRY violations, ...) | `pip install review-swarm` |
| **FixSwarm**     | Multi-agent code fixer -- propose, consensus, apply, regression-check; refuses fixes that move away from SOLID+DRY | `pip install fix-swarm-ai` |
| **DocSwarm**     | Documentation generator + ADR maintainer -- API docs, verification, SOLID/DRY trade-off justifications | `pip install doc-swarm-ai` |

All seven packages live in this monorepo under `packages/` but ship to PyPI independently. The shared code lives in `swarm-core`; layering enforced by `scripts/check_imports.py`.

## Quick Start

### Install

```bash
# Full suite
pip install swarm-core swarm-kb review-swarm doc-swarm-ai fix-swarm-ai arch-swarm-ai spec-swarm-ai

# With PDF support for datasheets
pip install spec-swarm-ai[pdf]
```

For monorepo development, clone and run `python scripts/install_all.py` (editable install across all packages in dependency order).

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

The suite follows a 9-stage pipeline (idea -> production) with **user gates** between stages. You control the pace -- no automatic progression. See `docs/architecture/pipeline-stages.md` for the full stage spec.

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

## SOLID + DRY -- the non-negotiable

Every expert profile in every tool ends with the same SOLID+DRY block (canonical home: `packages/swarm-core/src/swarm_core/experts/SOLID_DRY_BLOCK.md`). When AI agents drive the suite, they:

- **arch-swarm experts** propose designs that satisfy SRP, OCP, LSP, ISP, DIP and identify a single source of truth for every concern.
- **review-swarm experts** flag SOLID violations (god classes, layer-direction violations, fat interfaces) and DRY violations (logic duplicated across files) as `category: design` findings.
- **fix-swarm experts** propose fixes that move *toward* SOLID+DRY, never away. A fix that adds a god method is rejected.
- **doc-swarm experts** document decisions in terms of which SOLID/DRY trade-off was made.
- **spec-swarm experts** map hardware constraints to module boundaries that respect DIP.

This is the user-visible promise. Editing an expert YAML to weaken or remove the SOLID+DRY block is enforced by tests in `swarm-core` and by the `claude_md_keeper` audit at every `kb_advance_pipeline` call.

## Contributing

- Read `CLAUDE.md` first -- it's the rules, not a reference.
- Run `python scripts/verify_e2e.py` before opening a PR. It exercises the full surface (CLIs, MCP server wiring, every new pipeline stage end-to-end, prompt composition through subprocess, idempotency of all migration scripts, then the pytest sweep). 48 checks total.
- For a quick gate: `python scripts/check_imports.py && python scripts/test_all.py -q --tb=no`.
- Bugs / fixes / decisions go into `docs/decisions/<date>-<slug>.md`, NOT into CLAUDE.md.
- See `docs/INDEX.md` for the master keyword map.

## License

MIT -- [Ilya Sidorov](https://github.com/fozzfut)
