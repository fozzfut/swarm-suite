# Swarm Suite

**A multi-agent MCP toolkit that takes a Python project from idea to production.** Seven tools collaborate through a shared knowledge base to capture ideas, architect, plan, review, fix, document, harden, and release your code -- enforcing **SOLID + DRY** at every stage.

> Python-first and language-agnostic for everything below the spec layer. Embedded / industrial projects get an **optional** Stage 0 (`spec-swarm`) for datasheet + protocol analysis; everything else runs by default and works for any Python codebase.

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

## About

The suite was originally built for developers writing **industrial / embedded software**, where hardware specs (registers, pin maps, fieldbus protocols) need to align with the code architecture. That use case is still first-class via `spec-swarm`.

But the rest of the pipeline -- multi-agent architecture debates, multi-expert code review, fix-with-consensus, generate-verify-retry loops, the 13-format debate library, the AgentRearrange-style flow DSL, task-conditioned skill composition -- turned out general enough that **any Python project benefits**. Spec-swarm is opt-in (`include_spec=True`); everything else runs by default.

## Packages

Universal Python tooling (run by default):

| Package | Description | Install |
|---------|-------------|---------|
| **swarm-core**   | Shared foundation: models, expert registry, session lifecycle, coordination primitives, MCP scaffolding, CLAUDE.md keeper | `pip install swarmsuite-core` |
| **swarm-kb**     | Shared knowledge base -- findings, decisions, debates, judgings, verifications, pgve sessions, flow DSL, pipelines, code maps | `pip install swarm-kb` |
| **ArchSwarm**    | Multi-agent architecture debates -- coupling, modularity, scalability, SOLID-grounded designs | `pip install arch-swarm-ai` |
| **ReviewSwarm**  | Multi-agent code review -- 13 experts (security, performance, threading, SOLID/DRY violations, ...) | `pip install review-swarm` |
| **FixSwarm**     | Multi-agent code fixer -- propose, consensus, apply, regression-check; refuses fixes that move away from SOLID+DRY | `pip install fix-swarm-ai` |
| **DocSwarm**     | Documentation generator + ADR maintainer -- API docs, verification, SOLID/DRY trade-off justifications | `pip install doc-swarm-ai` |

Optional add-on for embedded / industrial projects:

| Package | Description | Install |
|---------|-------------|---------|
| **SpecSwarm**    | Hardware spec analyzer -- datasheets, register maps, CAN/CANopen/EtherCAT/PROFINET/Modbus/OPC UA. Activates Stage 0 of the pipeline (`include_spec=True`). Skip if you're not writing firmware / instrument software. | `pip install spec-swarm-ai` |

All packages live in this monorepo under `packages/` but ship to PyPI independently. The shared code lives in `swarm-core`; layering enforced by `scripts/check_imports.py`.

## Quick Start

### Install

```bash
# Default install -- universal Python tooling (skip spec-swarm if you're not on embedded)
pip install swarmsuite-core swarm-kb arch-swarm-ai review-swarm fix-swarm-ai doc-swarm-ai

# Embedded / industrial projects: add the spec analyzer
pip install spec-swarm-ai
pip install spec-swarm-ai[pdf]                 # for PDF datasheet ingestion

# Monorepo dev install (editable, dependency-ordered)
git clone https://github.com/fozzfut/swarm-suite
cd swarm-suite
python scripts/install_all.py
```

> **Naming note:** the foundation package is `swarmsuite-core` on PyPI (the shorter `swarm-core` was rejected as too similar to existing `swarms`). The Python import name remains `swarm_core` -- code and docs unchanged.

To verify the install: `python scripts/verify_e2e.py --quick` -- runs 47 end-to-end checks across CLIs, MCP server wiring, every new pipeline stage, prompt composition, and migration-script idempotency.

### Add MCP servers (Claude Code)

```bash
# Universal set
claude mcp add swarm-kb     -- swarm-kb serve --transport stdio
claude mcp add arch-swarm   -- arch-swarm serve --transport stdio
claude mcp add review-swarm -- review-swarm serve --transport stdio
claude mcp add fix-swarm    -- fix-swarm serve --transport stdio
claude mcp add doc-swarm    -- doc-swarm serve --transport stdio

# Embedded / industrial only
claude mcp add spec-swarm   -- spec-swarm serve --transport stdio
```

### Add MCP servers (Cursor / Windsurf / Cline)

```json
{
  "mcpServers": {
    "swarm-kb":     { "url": "http://localhost:8788/sse" },
    "arch-swarm":   { "url": "http://localhost:8768/sse" },
    "review-swarm": { "url": "http://localhost:8765/sse" },
    "fix-swarm":    { "url": "http://localhost:8767/sse" },
    "doc-swarm":    { "url": "http://localhost:8766/sse" },
    "spec-swarm":   { "url": "http://localhost:8769/sse" }
  }
}
```

## Pipeline Workflow

The suite follows a multi-stage pipeline (idea -> production) with **user gates** between stages. You control the pace -- no automatic progression. See `docs/architecture/pipeline-stages.md` for the full stage spec.

### Default flow (any Python project)

```
kb_start_pipeline("./project")
```

```
Stage 1: Architecture Analysis (ArchSwarm)
  ├── Scan project metrics: coupling, complexity, dependencies
  ├── Multi-agent debates on design decisions (real AI analysis)
  └── Decisions become ADRs in swarm-kb
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

### Embedded / industrial variant (opt-in Stage 0)

```
kb_start_pipeline("./project", include_spec=True)
```

Adds a Stage 0 *before* the architecture analysis:

```
Stage 0: Spec Analysis (SpecSwarm)
  ├── Ingest datasheets, reference manuals
  ├── Extract: registers, pins, protocols, timing, power, memory
  ├── Check conflicts: pin collisions, bus overload, power budget
  └── Export constraints to swarm-kb (informs Stage 1 architecture)
  USER GATE: review specs → kb_advance_pipeline()
```

Stages 1-5 then run as in the default flow, with the hardware constraints flowing through ADRs into review and fix.

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
| **ArchSwarm** | 10 | Simplicity, modularity, reuse, scalability, trade-offs, API design, data modeling, testing strategy, dependencies, observability |
| **ReviewSwarm** | 13 | Security, performance, threading, error handling, API contracts, consistency, dead code, dependencies, logging, resources, tests, types, project context |
| **FixSwarm** | 8 | Refactoring, security fix, performance fix, type fix, error handling fix, test fix, dependency fix, compatibility fix |
| **DocSwarm** | 8 | API reference, tutorials, changelog, migration guides, architecture docs, inline docs, README quality, error messages |
| **SpecSwarm** *(optional)* | 9 | MCU peripherals, CAN/CANopen/EtherCAT/PROFINET/Modbus, power, sensors, motors, memory, timing, safety |

**Total: 48 expert profiles.** The 39 in the universal set are language-agnostic and apply to any Python project; the 9 SpecSwarm experts are domain-specific to embedded / industrial work. All YAML, customizable.

## Requirements

- Python 3.10+
- An MCP-compatible AI client (Claude Code, Cursor, Windsurf, Cline, etc.)
- For PDF datasheets (embedded only): `pip install spec-swarm-ai[pdf]`

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
