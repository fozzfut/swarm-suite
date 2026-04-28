<div align="center">

# Swarm Suite

**Your AI coding assistant, but with a whole engineering team behind it.**

Architects, reviewers, fixers, doc writers, hardening engineers — 53 specialised AI experts<br/>
that take a Python project from **idea to a tagged release**, with you in the driver's seat.

[![PyPI](https://img.shields.io/pypi/v/swarmsuite-core?label=swarmsuite-core)](https://pypi.org/project/swarmsuite-core/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)

[Guide](GUIDE.md) · [Architecture](docs/architecture/) · [Decisions](docs/decisions/) · [Changelog](CHANGELOG.md)

</div>

---

## What is Swarm Suite?

You're using Claude Code, Cursor, or another AI coding assistant. It writes code. It even fixes bugs. But shipping a real, production-grade Python project still takes you — running architecture reviews in your head, hunting for bugs across files, regenerating docs by hand, doing the release dance.

**Swarm Suite gives that work to a team of specialised agents.** They're not a single super-prompt. They're 53 distinct experts (security, performance, threading, SOLID violations, embedded protocols, …) that claim files in parallel, debate disagreements with formal voting, and refuse to ship anything that isn't tested, reviewed, and clean.

You stay in the driver's seat. There's a user gate between every stage of the pipeline — nothing auto-progresses, nothing auto-publishes. You can also just **talk to it in plain language** — name the suite (or use a `/swarm-*` slash command) and then describe what you want in any language your AI client understands ("swarm-suite, review the auth module", "swarm — пофиксь баги", "swarm-suite, ready to release?"). The navigator skill figures out which of the 84 tools to call, so you never have to. Naming the suite is what stops the request from being grabbed by another skill or MCP server you have installed.

Built and tested on **Claude Code**. Should work on any MCP-compatible client (**Cursor**, **Windsurf**, **Cline**, …) — same MCP servers, same tools — but those paths are not yet covered by our test matrix; expect rough edges and please file an issue if you hit one.

## Features

- **Full lifecycle, not just code-gen** — Idea → Architecture → Plan → Review → Fix → Verify → Doc → Hardening → Release. Each stage has its own experts and its own quality gate.
- **53 specialised experts** — `security-surface`, `performance`, `threading-safety`, `simplicity`, `data-modeling`, `mcu-peripherals`, … One agent doing everything is a generalist; this is a team.
- **Multi-agent debate, not single-shot prompts** — when experts disagree, they open a formal debate (13 supported formats: open, with-judge, trial, mediation, council, …) and resolve to an **ADR** (Architecture Decision Record — a short document that captures the chosen option, the alternatives considered, and the rationale, so future agents and humans can audit *why* the decision was made).
- **SOLID + DRY enforced by default** — every expert auto-loads the SOLID+DRY skill. Fixes that move the code *away* from those principles are rejected; reviews flag violations as design findings.
- **You stay in control** — gates between every stage. No auto-merge, no auto-publish. Release stage prepares the artifact and stops.
- **Plain-language driver** — the navigator skill turns "пофиксь баги" or "ready to ship?" into the right sequence of MCP calls, in whichever language your AI client speaks. The 84 tools are an implementation detail.
- **Vendor-neutral and self-hosted** — runs on your machine, talks to your AI client over MCP, stores state in `~/.swarm-kb/`. No SaaS dependency.

---

## Install

```bash
# Universal Python tooling (recommended)
pip install swarmsuite-core swarm-kb arch-swarm-ai review-swarm fix-swarm-ai doc-swarm-ai

# Embedded / industrial projects: add the hardware spec analyzer
pip install spec-swarm-ai           # CAN/CANopen/EtherCAT/PROFINET/Modbus/OPC UA/...
pip install spec-swarm-ai[pdf]      # + datasheet PDF ingestion

# Monorepo dev install (editable, dependency-ordered)
git clone https://github.com/fozzfut/swarm-suite
cd swarm-suite
python scripts/install_all.py
```

> **Naming note:** the foundation package is `swarmsuite-core` on PyPI; the Python import name is still `swarm_core`.

To verify the install: `python scripts/verify_e2e.py --quick` (47 end-to-end checks).

## Connect to your AI client

### Claude Code

```bash
claude mcp add swarm-kb     -- swarm-kb serve --transport stdio
claude mcp add arch-swarm   -- arch-swarm serve --transport stdio
claude mcp add review-swarm -- review-swarm serve --transport stdio
claude mcp add fix-swarm    -- fix-swarm serve --transport stdio
claude mcp add doc-swarm    -- doc-swarm serve --transport stdio
claude mcp add spec-swarm   -- spec-swarm serve --transport stdio   # embedded only
```

### Cursor / Windsurf / Cline (SSE)

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

---

## Your first session

### 1. Open your project in your AI client

Restart it once after running the `mcp add` commands so the servers are picked up.

### 2. Use a slash command, or name the suite explicitly

Slash commands like `/swarm-review` are unambiguous — they always route here. They're the **safest way to invoke the suite**:

```
/swarm-review packages/auth
```

You can also use plain language (any language your AI client speaks), but **mention "swarm" or "swarm-suite" by name** so it doesn't collide with other skills or MCP servers you may have installed (Claude Code's own `/review`, other code-review MCPs, etc.):

```
You: запусти swarm-suite review на packages/auth

AI:  Starting a swarm-suite code review on packages/auth. 13 experts will
     claim files in parallel, then a cross-check phase reconciles findings.
```

Without that explicit mention, a request like *"review this code"* may trigger a different tool entirely. The navigator skill is loaded by swarm-suite's MCP servers, but it has no way to override your AI client's other capabilities — naming the suite is what disambiguates.

Under the hood the slash command expands to `kb_start_pipeline → review_start_session → orchestrate_review → kb_post_finding × N → mark_phase_done`. You don't need to know that.

### 3. Watch the experts work

Each expert claims a file, posts findings (with severity, file:line, evidence), then a cross-check phase runs where experts react to each other's findings (`confirm`, `dispute`, `duplicate`). The output is a triaged finding list, not 50 noisy comments.

### 4. Move to the next stage when you're ready

```
You: looks good, fix the high-severity ones

AI:  Starting fix stage. 16 high-severity findings to address. I'll propose
     fixes one at a time, run the test suite after each, and stop if anything
     regresses. Quality gate: max 0 critical, max 3 high remaining.
```

You can stop at any stage. You can rewind to an earlier stage if a later one surfaces a problem (`kb_rewind_pipeline`).

---

## A note on cost

Each stage spawns **multiple specialised agents working in parallel** — Stage 3 review uses up to 13 experts; Stage 1 architecture runs 10 experts plus debate participants; Stage 0b spec analysis up to 14. Every expert is a real LLM call. This is *intentional* — that's where quality comes from — but it has consequences:

- **Token usage adds up fast.** A full Idea → Release pipeline on a medium project can run into several million tokens. A focused single-stage review on one package is much smaller, but still 5–13× a regular chat.
- **Plan rate limits will be felt.** On Claude Pro / Max, a single full pipeline pass takes a meaningful share of your weekly budget. On API-key plans you'll see it on the bill. Sessions are resumable if you hit a limit mid-stage — restart the same `session_id` and the suite picks up where it left off.
- **Tune the scope before launching.** Prefer `/swarm-review packages/auth` over the whole project. Apply fixes one at a time with `/swarm-fix <finding_id>`. Skip optional stages (Idea / Plan / Doc) when you don't need them.
- **Lite mode for one-offs.** `kb_quick_review` / `kb_quick_fix` bypass the full pipeline ceremony — single expert, no consensus phase, no debate. Use these when you just want a second opinion on one snippet.
- **Watch the AgentRouter.** Stage 1 and 3 use `kb_route_experts` to pre-pick only the experts whose `relevance_signals` match your codebase, so you're not paying 13 calls for a CLI tool that has no networking code. Trust it; don't override unless you have a reason.

Production-grade quality is worth the cost — but go in with eyes open. If you're on a tight budget, start with `/swarm-review` on one package and decide whether to expand from there.

---

## Slash commands

Six built-in commands cover the most common workflows. They're shortcuts — you can always just describe what you want in plain language instead.

| Command | What it does |
|---------|--------------|
| `/swarm-help` | Brief orientation; lists all commands |
| `/swarm-status` | Show what's happening in the pipeline + 2–3 next-step options |
| `/swarm-next` | Pick the most-recommended next action and execute it |
| `/swarm-review [scope]` | Multi-expert code review (Stage 3) |
| `/swarm-fix [finding_id]` | Apply fixes for confirmed findings (Stage 4) |
| `/swarm-release` | Drive Hardening + Release prep (Stages 7–8). Never auto-publishes. |

Type `/` in Claude Code to see them inline. Slash commands are also installed by the `python scripts/install_all.py` step.

---

## The pipeline

Ten stages from idea to release. Optional stages are blue. Every solid arrow crosses a user gate (`kb_advance_pipeline`).

```mermaid
flowchart LR
    Start([Project])
    Idea["0a Idea<br/><i>optional</i>"]
    Spec["0b Spec<br/><i>embedded only</i>"]
    Arch["1 Architecture"]
    Plan["2 Plan<br/><i>optional</i>"]
    Review["3 Review"]
    Fix["4 Fix"]
    Verify["5 Verify"]
    Doc["6 Doc<br/><i>optional</i>"]
    Hard["7 Hardening"]
    Release["8 Release"]
    End([Ready])

    Start --> Idea --> Spec --> Arch --> Plan --> Review --> Fix --> Verify --> Doc --> Hard --> Release --> End

    classDef optional fill:#e1f5ff,stroke:#1976d2,color:#0d47a1
    classDef required fill:#f3f3f3,stroke:#424242,color:#212121
    classDef terminal fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    class Idea,Spec,Plan,Doc optional
    class Arch,Review,Fix,Verify,Hard,Release required
    class Start,End terminal
```

| Stage | What happens |
|-------|--------------|
| **0a Idea** _(optional, greenfield)_ | One-question-at-a-time brainstorming → `design.md` |
| **0b Spec** _(embedded only)_ | Datasheet ingestion → registers, pins, protocols, conflict report |
| **1 Architecture** | Project scan + multi-agent debates → ADRs |
| **2 Plan** _(optional, recommended for greenfield)_ | TDD-grade implementation plan, tasks of 2–5 minutes each |
| **3 Review** | 13 experts claim files in parallel, post findings, cross-check |
| **4 Fix** | Propose fixes → consensus voting → apply, with regression checks |
| **5 Verify** | Re-run tests, finalise verification report |
| **6 Doc** _(optional, run once near release)_ | Verify stale docs, regenerate API reference |
| **7 Hardening** | mypy / coverage / pip-audit / secret scan / observability checks |
| **8 Release** | Version bump (Conventional Commits) + changelog + dist build. **Never publishes.** |

For the full per-stage flow with every internal MCP call see [docs/architecture/pipeline-stages.md](docs/architecture/pipeline-stages.md). For the user-facing command reference see [GUIDE.md](GUIDE.md).

---

## What's inside

| Package | Purpose | PyPI |
|---------|---------|------|
| **swarm-core** | Shared foundation: models, expert registry, session lifecycle, coordination primitives, MCP scaffolding | `swarmsuite-core` |
| **swarm-kb** | Shared knowledge base: findings, decisions, debates, judgings, verifications, pipelines, code maps | `swarm-kb` |
| **arch-swarm** | Architecture debates — 10 experts (simplicity, modularity, scalability, …) | `arch-swarm-ai` |
| **review-swarm** | Code review — 13 experts (security, performance, threading, type-safety, …) | `review-swarm` |
| **fix-swarm** | Fix proposer + applier — 8 experts; refuses fixes that move away from SOLID+DRY | `fix-swarm-ai` |
| **doc-swarm** | Docs maintainer — 8 experts (API ref, README, ADR, changelog, …) | `doc-swarm-ai` |
| **spec-swarm** _(optional)_ | Hardware spec analyzer — 14 experts (MCU, fieldbus, safety, …) | `spec-swarm-ai` |

For the full list of all 53 expert profiles see [GUIDE.md § Expert Profiles](GUIDE.md#expert-profiles).

## Architecture

```
                +-----------------+
                |   swarm-core    |  models, ExpertRegistry, SessionLifecycle,
                |                 |  MessageBus / EventBus / PhaseBarrier,
                |                 |  RateLimiter, MCPApp, skill composition
                +--------+--------+
                         |
                +--------v--------+
                |    swarm-kb     |  findings, decisions, debates, judgings,
                |                 |  verifications, pgve sessions, flows,
                |                 |  pipelines, code maps, quality gate
                +-+-+-+-+-+-+-+-+-+
                  | | | | | | | |
       +----------+ | | | | | | +----------+
       |          | | | | | | |            |
       v          v v v v v v v            v
     spec-      arch-  review-  fix-    doc-
     swarm      swarm   swarm   swarm   swarm
```

**The five `*-swarm` tools never depend on each other.** They communicate only through `swarm-kb`. Adding a new tool means dropping a new package — existing tools don't notice. Layering enforced by `scripts/check_imports.py` in CI.

For deeper architecture see [docs/architecture/](docs/architecture/): [layering](docs/architecture/layering.md), [session-storage](docs/architecture/session-storage.md), [coordination-primitives](docs/architecture/coordination-primitives.md), [skill-composition](docs/architecture/skill-composition.md).

---

## Documentation

| If you want | Read |
|-------------|------|
| The full pipeline reference + every command | [GUIDE.md](GUIDE.md) |
| Architecture deep-dives | [docs/architecture/](docs/architecture/) |
| Per-feature docs | [docs/features/](docs/features/) |
| Decisions / post-mortems | [docs/decisions/](docs/decisions/) |
| Master keyword index | [docs/INDEX.md](docs/INDEX.md) |
| Rules of engagement (philosophy) | [CLAUDE.md](CLAUDE.md) |

## Requirements

- Python 3.10+
- An MCP-compatible AI client (Claude Code, Cursor, Windsurf, Cline, …)
- For embedded PDF datasheets: `pip install spec-swarm-ai[pdf]`

## Contributing

- Read [CLAUDE.md](CLAUDE.md) first — it's the rules, not a reference.
- Run `python scripts/verify_e2e.py` before opening a PR (47 checks: CLIs, MCP wiring, every stage end-to-end, prompt composition, migration idempotency).
- Quick gate: `python scripts/check_imports.py && python scripts/test_all.py -q --tb=no`.
- Bugs / fixes / decisions go into `docs/decisions/<date>-<slug>.md`, **not** into CLAUDE.md.
- See [docs/INDEX.md](docs/INDEX.md) for the master keyword map.

## License

MIT — [Ilya Sidorov](https://github.com/fozzfut)
