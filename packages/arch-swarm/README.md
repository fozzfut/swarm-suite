# arch-swarm

> **Part of [Swarm Suite](https://github.com/fozzfut/swarm-suite).** Most users install the whole suite and drive it through the [main README](../../README.md) and `/swarm-*` slash commands — they never read this file. This README documents the package itself for contributors and standalone users.

Multi-agent **architecture analysis and design debate**. Ten specialised expert agents (simplicity, modularity, reuse, scalability, trade-off mediator, API design, data modeling, testing strategy, dependency architecture, observability) propose, critique, and vote on design decisions, resolving each debate to an **ADR** (Architecture Decision Record).

This is **Stage 1** of the Swarm Suite pipeline: project scan + multi-agent debates → ADRs that subsequent stages (Plan, Review, Fix) treat as authoritative context.

## Install

```bash
pip install arch-swarm-ai
```

## Connect to your AI client

```bash
# Claude Code (built and tested)
claude mcp add arch-swarm -- arch-swarm serve --transport stdio
```

For Cursor / Windsurf / Cline (untested but should work via MCP), see the main [README § Connect to your AI client](../../README.md#connect-to-your-ai-client).

## CLI (standalone usage)

```bash
arch-swarm analyze . --scope src/         # quick automated metrics + findings
arch-swarm debate . --topic "..."          # start a multi-agent design debate
arch-swarm report <session-id>             # view debate transcript + ADRs
```

## Expert profiles (10)

| Slug | Specialisation |
|------|----------------|
| `simplicity` | Champions minimal solutions; flags over-engineering. |
| `modularity` | Module boundaries, single responsibility, coupling metrics. |
| `reuse` | Code duplication, missed shared abstractions. |
| `scalability` | Stress-tests designs against growth scenarios. |
| `tradeoff-mediator` | Synthesises competing perspectives; documents trade-offs. |
| `api-design` | Naming consistency, versioning, backward compatibility. |
| `data-modeling` | Schema design, normalization, migration safety. |
| `testing-strategy` | Test architecture, pyramid balance, fixture strategy. |
| `dependency-architecture` | Dependency graph direction, layer enforcement. |
| `observability` | Logging architecture, metrics design, alerting strategy. |

Every expert auto-loads the universal **SOLID + DRY** and **karpathy-guidelines** skills via the composition mechanism. See [`docs/architecture/skill-composition.md`](../../docs/architecture/skill-composition.md).

## Cost

Each debate spawns multiple LLM calls in parallel — see the main [README § A note on cost](../../README.md#a-note-on-cost) before launching.

## License

MIT — [Ilya Sidorov](https://github.com/fozzfut)
