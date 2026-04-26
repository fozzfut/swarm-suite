# Swarm Suite Docs Index

Master keyword index. Use this to find the right doc fast; CLAUDE.md
intentionally does not duplicate the detail.

## Where to look

| If you want | Read this |
|-------------|-----------|
| The non-negotiable rules / philosophy | `/CLAUDE.md` |
| The user-facing pipeline + commands | `/GUIDE.md` |
| Why a particular design / fix exists (post-mortems, ADRs) | `/docs/decisions/` |
| Architecture deep-dives (layering, schema, MCP) | `/docs/architecture/` |
| How a single feature works end-to-end | `/docs/features/` |
| API of one package | `/packages/<name>/README.md` |

## Architecture docs

- [layering](architecture/layering.md) -- four layers, who imports whom, the import-direction CI gate.
- [expert-profile-format](architecture/expert-profile-format.md) -- YAML schema, required fields, the SOLID+DRY block contract.
- [session-storage](architecture/session-storage.md) -- `~/.swarm-kb/` layout, JSONL semantics, atomic writes.
- [mcp-server-pattern](architecture/mcp-server-pattern.md) -- `MCPApp`, transport, error wrapping, structured logging.
- [coordination-primitives](architecture/coordination-primitives.md) -- MessageBus, EventBus, PhaseBarrier, ClaimRegistry, RateLimiter.
- [pipeline-stages](architecture/pipeline-stages.md) -- Idea -> ... -> Release, gates, what each stage produces.
- [skill-composition](architecture/skill-composition.md) -- methodology recipes + composition into expert prompts (universal vs opt-in, layered discipline).

## Feature docs (per pipeline stage)

- [features/spec-analysis](features/spec-analysis.md) -- SpecSwarm: datasheets, registers, conflicts.
- [features/architecture-debate](features/architecture-debate.md) -- ArchSwarm: propose / critique / vote.
- [features/code-review](features/code-review.md) -- ReviewSwarm: claim / review / cross-check.
- [features/fix-cycle](features/fix-cycle.md) -- FixSwarm: propose / consensus / apply / regression.
- [features/documentation](features/documentation.md) -- DocSwarm: scan / verify / generate.
- [features/quality-gate](features/quality-gate.md) -- thresholds, circuit breaker, gate flow.

## Decisions / post-mortems

- [2026-04-26 fix-swarm <- arch-swarm coupling](decisions/2026-04-26-fix-swarm-arch-coupling.md)
- [2026-04-26 swarm-core extraction roadmap](decisions/2026-04-26-swarm-core-extraction.md)
- [2026-04-26 skill composition design](decisions/2026-04-26-skill-composition.md)
- [2026-04-26 Stage 0a Idea contract](decisions/2026-04-26-stage-0a-idea-stage.md)
- [2026-04-26 Stage 2 Plan contract](decisions/2026-04-26-stage-2-plan-stage.md)
- [2026-04-26 Stages 6 + 7 Hardening + Release contracts](decisions/2026-04-26-stages-6-7-hardening-release.md)
- [2026-04-26 skill composition gap (open)](decisions/2026-04-26-skill-composition-gap.md)
- [2026-04-26 real-work review findings (resolved)](decisions/2026-04-26-real-work-review.md)

## Plans (in progress)

(empty for now -- live plans go in `docs/plans/<date>-<slug>.md`)

## Keywords -> docs map

| Keyword | Where |
|---------|-------|
| atomic write, tempfile, os.replace | architecture/session-storage |
| JSONL, append-only | architecture/session-storage |
| schema_version, forward-compatible | CLAUDE.md (Schema Versioning); architecture/session-storage |
| MCP transport, stdio, sse | architecture/mcp-server-pattern |
| McpError, error wrapping | architecture/mcp-server-pattern; CLAUDE.md (MCP Tool Contract) |
| expert YAML, system_prompt, SOLID+DRY block | architecture/expert-profile-format |
| layering, import direction | architecture/layering; scripts/check_imports.py |
| ClaimRegistry, TOCTOU | architecture/coordination-primitives; CLAUDE.md (Concurrency) |
| PhaseBarrier, phase_done | architecture/coordination-primitives |
| RateLimiter, sliding window | architecture/coordination-primitives |
| MessageBus, pub/sub | architecture/coordination-primitives |
| EventBus, replay | architecture/coordination-primitives |
| SessionLifecycle, session_id format | architecture/session-storage |
| pipeline gate, kb_advance_pipeline | architecture/pipeline-stages; features/quality-gate |
| quality gate, max_critical, circuit breaker | features/quality-gate |
| CLAUDE.md keeper, audit | architecture/expert-profile-format (Keeper section); CLAUDE.md ("What CLAUDE.md Is") |
| SOLID, DRY, principles | CLAUDE.md (Architecture Principles); architecture/expert-profile-format |
